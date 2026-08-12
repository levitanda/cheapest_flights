"""Deciding whether a fare is genuinely unusual.

Two independent tests, in priority order:

1. **Statistical** — once a route has enough history, compare the fare against
   its own median. A fare has to be both far below the median in relative
   terms (`min_drop_pct`) and far below it in units of the route's own
   volatility (`min_z_score`), and be at or under the 10th percentile of
   everything seen. Requiring all three is what keeps a noisy route from
   firing constantly: a route that swings 40% every week has a wide MAD, so a
   40% drop scores a low z and stays quiet, while the same drop on a stable
   route pages immediately.

2. **Heuristic** — with no usable history, fall back to what the distance says
   the flight should cost. Deliberately conservative (roughly half of expected
   before it fires) because the curve is crude, and every alert from this path
   is labelled as such so the reader knows the evidence is weaker.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import Settings
from .geo import Geo
from .models import (
    TIER_ERROR_FARE,
    TIER_EXCEPTIONAL,
    TIER_GOOD,
    TIER_GREAT,
    Baseline,
    Deal,
    Offer,
)
from .storage import Storage

logger = logging.getLogger(__name__)


class Detector:
    def __init__(self, settings: Settings, storage: Storage, geo: Optional[Geo] = None) -> None:
        self.settings = settings
        self.storage = storage
        self.geo = geo

    # -- public -------------------------------------------------------------

    def evaluate(self, offer: Offer) -> Optional[Deal]:
        """Return a Deal if the offer is anomalous, else None."""
        if offer.price <= 0:
            return None

        baseline = self.storage.baseline(
            offer.origin,
            offer.destination,
            offer.trip_kind,
            offer.currency,
            self.settings.baseline_window_days,
        )
        if baseline and self._is_reliable(baseline):
            return self._evaluate_statistical(offer, baseline)
        return self._evaluate_heuristic(offer)

    # -- paths --------------------------------------------------------------

    def _is_reliable(self, baseline: Baseline) -> bool:
        """History is trustworthy only if it is both deep and spread out.

        Sample size alone is not enough: 200 fares all scraped in one sweep
        describe a single moment, not a normal price. Requiring several
        distinct days is what makes the median mean anything.
        """
        return (
            baseline.sample_size >= self.settings.min_observations
            and baseline.distinct_days >= self.settings.min_distinct_days
            and baseline.median > 0
        )

    def _evaluate_statistical(self, offer: Offer, baseline: Baseline) -> Optional[Deal]:
        drop_pct = (baseline.median - offer.price) / baseline.median
        z_score = (baseline.median - offer.price) / baseline.robust_sigma

        if drop_pct < self.settings.min_drop_pct:
            return None
        if z_score < self.settings.min_z_score:
            return None
        if offer.price > baseline.p10:
            return None

        reason = (
            f"на {drop_pct:.0%} ниже обычной цены маршрута "
            f"({baseline.median:.0f} {baseline.currency.upper()}, "
            f"{baseline.sample_size} наблюдений за {baseline.distinct_days} дней)"
        )
        return Deal(
            offer=offer,
            baseline_price=baseline.median,
            drop_pct=drop_pct,
            z_score=z_score,
            tier=self._tier(drop_pct, z_score, basis="history"),
            basis="history",
            reason=reason,
        )

    def _evaluate_heuristic(self, offer: Offer) -> Optional[Deal]:
        if self.geo is None:
            return None
        expected_usd = self.geo.expected_price(
            offer.origin, offer.destination, one_way=offer.trip_kind == "ow"
        )
        if not expected_usd:
            return None

        expected = expected_usd * self.settings.usd_rate
        if offer.price > expected * self.settings.cold_start_ratio:
            return None

        drop_pct = (expected - offer.price) / expected
        distance = self.geo.distance_km(offer.origin, offer.destination) or 0
        reason = (
            f"истории по маршруту пока нет; для {distance:.0f} км ожидаемая цена "
            f"около {expected:.0f} {offer.currency.upper()}, что на {drop_pct:.0%} дороже"
        )
        return Deal(
            offer=offer,
            baseline_price=expected,
            drop_pct=drop_pct,
            # No per-route history means no meaningful volatility to divide by.
            z_score=0.0,
            tier=self._tier(drop_pct, 0.0, basis="heuristic"),
            basis="heuristic",
            reason=reason,
        )

    # -- grading ------------------------------------------------------------

    def _tier(self, drop_pct: float, z_score: float, basis: str) -> str:
        if drop_pct >= self.settings.error_fare_drop_pct and basis == "history":
            # A 70%-off fare on a route we know well is usually a pricing
            # mistake rather than a sale, and those get withdrawn within hours.
            return TIER_ERROR_FARE
        if drop_pct >= 0.55 or z_score >= 4.0:
            return TIER_EXCEPTIONAL
        if drop_pct >= 0.45 or z_score >= 3.0:
            return TIER_GREAT
        return TIER_GOOD

    # -- alert gating -------------------------------------------------------

    def should_alert(self, deal: Deal) -> bool:
        """Suppress repeats of something the user has already been told.

        Two gates: an exact fingerprint we have sent before, and a softer
        per-route cooldown that only lets a re-alert through if the new fare
        beats the last one by a real margin.
        """
        if self.storage.seen_fingerprint(deal.fingerprint):
            return False

        previous = self.storage.last_alert_price(
            deal.offer.origin,
            deal.offer.destination,
            deal.offer.trip_kind,
            deal.offer.depart_month,
            self.settings.alert_cooldown_hours,
        )
        if previous is None:
            return True
        improvement = (previous - deal.offer.price) / previous
        return improvement >= self.settings.alert_improve_pct
