"""One scan pass: collect, store, judge, notify.

Ordering here is deliberate. Offers are judged against the baseline *before*
they are written to history, so a fare never dilutes the very median it is
being compared to. On a route with few observations, storing first would let
an error fare drag the median down far enough to disqualify itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .config import Settings
from .detector import Detector
from .geo import Geo
from .models import Deal, Offer
from .notify import Notifier
from .providers.base import PriceProvider
from .storage import Storage
from .watchlist import MODE_TRACK, WatchEntry

logger = logging.getLogger(__name__)


@dataclass
class ScanReport:
    offers_seen: int = 0
    offers_stored: int = 0
    enriched: int = 0
    candidates: int = 0
    alerted: int = 0
    suppressed: int = 0
    errors: list[str] = field(default_factory=list)
    deals: list[Deal] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.offers_seen} предложений",
            f"{self.candidates} кандидатов",
            f"{self.alerted} отправлено",
        ]
        if self.suppressed:
            parts.append(f"{self.suppressed} подавлено")
        if self.errors:
            parts.append(f"{len(self.errors)} ошибок")
        return ", ".join(parts)


def collect_offers(
    provider: PriceProvider,
    entry: WatchEntry,
    geo: Optional[Geo],
    report: ScanReport,
) -> list[Offer]:
    """Fetch everything one watchlist entry asks for, filtered by its rules."""
    raw: list[Offer] = []
    try:
        if entry.mode == MODE_TRACK and entry.destination:
            for month in entry.months():
                raw.extend(
                    provider.prices_for_dates(
                        entry.origin,
                        entry.destination,
                        departure_at=month,
                        direct=entry.direct_only,
                    )
                )
        else:
            raw.extend(provider.city_directions(entry.origin))
    except Exception as exc:
        message = f"{entry.origin}->{entry.destination or '*'}: {exc}"
        logger.warning("fetch failed for %s", message)
        report.errors.append(message)
        return []

    kept = []
    for offer in raw:
        country = geo.country(offer.destination) if geo else ""
        if entry.accepts(offer, country):
            kept.append(offer)
    logger.info(
        "%s->%s: %d offers, %d after filters",
        entry.origin,
        entry.destination or "*",
        len(raw),
        len(kept),
    )
    return kept


def run_scan(
    settings: Settings,
    provider: PriceProvider,
    storage: Storage,
    watchlist: Sequence[WatchEntry],
    notifiers: Sequence[Notifier],
    geo: Optional[Geo] = None,
    dry_run: bool = False,
) -> ScanReport:
    report = ScanReport()
    detector = Detector(settings, storage, geo)

    all_offers: list[Offer] = []
    for entry in watchlist:
        all_offers.extend(collect_offers(provider, entry, geo, report))
    report.offers_seen = len(all_offers)

    # The discovery sweep returns prices without a bookable link. Resolve them
    # before anything is stored or judged, so both the page and the alerts can
    # point at the actual fare instead of a generic search.
    enrich = getattr(provider, "enrich", None)
    if enrich is not None and all_offers:
        try:
            all_offers = list(enrich(all_offers, settings.enrich_limit))
        except Exception as exc:
            logger.warning("deep-link enrichment failed, continuing: %s", exc)
    report.enriched = sum(1 for o in all_offers if o.deep_link)

    # Judge everything first, against history as it stood before this sweep.
    candidates: list[Deal] = []
    for offer in all_offers:
        deal = detector.evaluate(offer)
        if deal:
            candidates.append(deal)
    report.candidates = len(candidates)

    report.offers_stored = storage.record_offers(all_offers)

    # Loudest and deepest first, so the per-scan cap keeps the best ones.
    candidates.sort(key=lambda d: d.rank, reverse=True)

    sent = 0
    for deal in candidates:
        if sent >= settings.max_alerts_per_scan:
            report.suppressed += 1
            continue
        if not detector.should_alert(deal):
            report.suppressed += 1
            continue

        booking_url = provider.booking_url(deal.offer)
        report.deals.append(deal)

        if dry_run:
            for notifier in notifiers:
                if notifier.name == "console":
                    notifier.send(deal, booking_url)
            sent += 1
            continue

        delivered = any(notifier.send(deal, booking_url) for notifier in notifiers)
        if delivered:
            # Recorded only on success, so a Telegram outage doesn't silently
            # burn the alert — the next scan will retry it.
            storage.record_alert(deal, url=booking_url)
            sent += 1
        else:
            report.errors.append(f"delivery failed for {deal.offer.route}")

    report.alerted = sent
    return report
