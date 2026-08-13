"""Travelpayouts / Aviasales data API.

Chosen over Amadeus and Skyscanner for this use case because the free tier is
generous, no partner approval is needed, and Aviasales has genuinely good
coverage of Israeli departures — which is exactly the gap that made the
off-the-shelf deal clubs useless here.

Two endpoints carry the whole product:

  v1/city-directions      one call, cheapest fare from TLV to everywhere
  v3/prices_for_dates     drill-down on a single route, month by month

Both report fares Aviasales users actually found in the last 48 hours, so the
data is already biased towards bookable prices rather than published tariffs.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

import requests

from ..models import Offer

logger = logging.getLogger(__name__)

_BASE = "https://api.travelpayouts.com"
_SEARCH_HOST = "https://www.aviasales.com"
_RETRY_DELAYS = (1.0, 3.0, 8.0)
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _parse_date(value: Any) -> Optional[date]:
    """Accept the several shapes the API uses for a date field."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    # Full timestamps come with an offset ("2026-09-12T05:30:00+03:00") and
    # sometimes with a trailing Z, which fromisoformat rejects before 3.11.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        logger.debug("unparseable date %r", value)
        return None


def _as_float(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TravelpayoutsProvider:
    name = "travelpayouts"

    def __init__(
        self,
        token: str,
        currency: str = "usd",
        marker: str = "",
        timeout: int = 20,
        session: Optional[requests.Session] = None,
        market: str = "il",
    ) -> None:
        if not token:
            raise ValueError("TRAVELPAYOUTS_TOKEN is required")
        self.token = token
        self.currency = currency.lower()
        self.marker = marker
        self.timeout = timeout
        # Without this the API answers for the Russian market, which is how a
        # Tel Aviv sweep ended up recommending Ufa and Chelyabinsk.
        self.market = market.lower()
        self.session = session or requests.Session()

    # -- transport ----------------------------------------------------------

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "token": self.token}
        url = f"{_BASE}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                # Transport-level failure: worth another go.
                last_error = exc
                if attempt >= len(_RETRY_DELAYS):
                    break
                time.sleep(_RETRY_DELAYS[attempt])
                continue

            if resp.status_code in _RETRY_STATUS:
                if attempt >= len(_RETRY_DELAYS):
                    last_error = RuntimeError(f"HTTP {resp.status_code}")
                    break
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "%s returned %s, retrying in %.0fs", path, resp.status_code, delay
                )
                time.sleep(delay)
                continue

            if resp.status_code >= 400:
                # A bad token or a malformed route will fail identically on
                # every retry, so surface it now instead of after four sleeps.
                raise RuntimeError(f"{path}: HTTP {resp.status_code} {resp.text[:200]}")

            try:
                payload = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"{path}: response was not JSON ({exc})") from exc

            if isinstance(payload, dict) and payload.get("success") is False:
                raise RuntimeError(f"{path}: {payload.get('error') or 'request rejected'}")
            return payload if isinstance(payload, dict) else {"data": payload}

        raise RuntimeError(f"{path} failed after retries: {last_error}")

    # -- endpoints ----------------------------------------------------------

    def city_directions(self, origin: str) -> Sequence[Offer]:
        payload = self._get(
            "/v1/city-directions",
            {"origin": origin.upper(), "currency": self.currency, "market": self.market},
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return []

        now = datetime.now(timezone.utc)
        offers = []
        for destination, row in data.items():
            if not isinstance(row, dict):
                continue
            offer = self._offer(
                origin=row.get("origin") or origin,
                destination=row.get("destination") or destination,
                row=row,
                observed_at=now,
            )
            if offer:
                offers.append(offer)
        return offers

    def latest_prices(self, origin: str, limit: int = 1000) -> Sequence[Offer]:
        """Every route the API has recently seen from `origin`, in one call.

        `city-directions` only answers for destinations it holds a cached
        cheapest fare for — from Tel Aviv that was 29 of them, missing
        Amsterdam, London, Barcelona and most of western Europe. This endpoint
        returns the raw recent finds instead, which is far broader coverage
        for the same single request.
        """
        payload = self._get(
            "/v2/prices/latest",
            {
                "origin": origin.upper(),
                "currency": self.currency,
                "market": self.market,
                "period_type": "year",
                "one_way": "false",
                "show_to_affiliates": "true",
                "sorting": "price",
                "limit": min(limit, 1000),
            },
        )
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            return []

        now = datetime.now(timezone.utc)
        offers = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            offer = self._offer(
                origin=row.get("origin") or origin,
                destination=row.get("destination") or "",
                row=row,
                observed_at=now,
            )
            if offer and offer.destination:
                offers.append(offer)
        return offers

    def prices_for_dates(
        self,
        origin: str,
        destination: str,
        departure_at: Optional[str] = None,
        return_at: Optional[str] = None,
        one_way: bool = False,
        direct: bool = False,
        limit: int = 100,
    ) -> Sequence[Offer]:
        params: dict[str, Any] = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "currency": self.currency,
            "market": self.market,
            "sorting": "price",
            "unique": "false",
            "limit": min(limit, 1000),
            "one_way": "true" if one_way else "false",
            "direct": "true" if direct else "false",
        }
        if departure_at:
            params["departure_at"] = departure_at
        if return_at:
            params["return_at"] = return_at

        payload = self._get("/aviasales/v3/prices_for_dates", params)
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            return []

        now = datetime.now(timezone.utc)
        offers = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            offer = self._offer(
                origin=row.get("origin") or origin,
                destination=row.get("destination") or destination,
                row=row,
                observed_at=now,
            )
            if offer:
                offers.append(offer)
        return offers

    # -- mapping ------------------------------------------------------------

    def enrich(self, offers: Sequence[Offer], limit: int = 30) -> list[Offer]:
        """Fetch a real deep link for offers that arrived without one.

        `city-directions` — the sweep that finds most destinations — returns a
        price but no `link`, so those fares could only ever point at a generic
        search. That is precisely the "here is the price, here is nowhere to
        buy it" failure this service exists to avoid.

        One call per destination, not per offer. The broad sweep returns
        hundreds of fares clustered on a few popular routes, so picking the
        globally cheapest N would spend the whole budget resolving Larnaca
        twelve times while Amsterdam kept pointing at a search.
        """
        best_per_route: dict[tuple[str, str, str], Offer] = {}
        for offer in offers:
            if offer.deep_link or not offer.depart_date:
                continue
            key = (offer.origin, offer.destination, offer.trip_kind)
            current = best_per_route.get(key)
            if current is None or offer.price < current.price:
                best_per_route[key] = offer

        linkless = sorted(best_per_route.values(), key=lambda o: o.price)[:limit]
        if not linkless:
            return list(offers)

        replacements: dict[int, Offer] = {}
        for offer in linkless:
            try:
                found = self.prices_for_dates(
                    offer.origin,
                    offer.destination,
                    departure_at=offer.depart_date.strftime("%Y-%m"),
                    one_way=offer.return_date is None,
                    limit=100,
                )
            except Exception as exc:
                logger.debug("enrich failed for %s: %s", offer.route, exc)
                continue

            match = self._best_match(offer, found)
            if match is not None:
                replacements[id(offer)] = match

        if replacements:
            logger.info("enriched %d/%d offers with a real deep link",
                        len(replacements), len(linkless))
        return [replacements.get(id(o), o) for o in offers]

    @staticmethod
    def _best_match(offer: Offer, candidates: Sequence[Offer]) -> Optional[Offer]:
        """Pick the candidate that genuinely corresponds to `offer`.

        Preference order: same departure date, then no more expensive than
        what we already reported. Returning a pricier itinerary would make the
        page lie about the fare it is linking to.
        """
        usable = [c for c in candidates if c.deep_link]
        if not usable:
            return None

        same_day = [c for c in usable if c.depart_date == offer.depart_date]
        pool = same_day or usable
        cheapest = min(pool, key=lambda c: c.price)
        return cheapest if cheapest.price <= offer.price * 1.02 else None

    def _offer(
        self, origin: str, destination: str, row: dict, observed_at: datetime
    ) -> Optional[Offer]:
        price = _as_float(row.get("price") or row.get("value"))
        if price is None:
            return None
        return Offer(
            origin=str(origin),
            destination=str(destination),
            price=price,
            currency=str(row.get("currency") or self.currency),
            depart_date=_parse_date(
                row.get("departure_at") or row.get("depart_date")
            ),
            return_date=_parse_date(
                row.get("return_at") or row.get("return_date")
            ),
            transfers=_as_int(
                row.get("transfers")
                if row.get("transfers") is not None
                else row.get("number_of_changes")
            ),
            airline=row.get("airline") or None,
            deep_link=row.get("link") or None,
            # Present on some responses, absent on others; when it is there we
            # can name the actual seller instead of saying "Aviasales".
            seller=row.get("gate") or row.get("agency") or None,
            source=self.name,
            observed_at=observed_at,
        )

    def booking_url(self, offer: Offer) -> str:
        return booking_url(
            offer.origin,
            offer.destination,
            offer.depart_date,
            offer.return_date,
            offer.deep_link,
            self.marker,
        )


def booking_url(
    origin: str,
    destination: str,
    depart_date: Optional[date] = None,
    return_date: Optional[date] = None,
    deep_link: Optional[str] = None,
    marker: str = "",
) -> str:
    """Prefer the API's own deep link; fall back to a search URL.

    `link` is a site-relative path that already encodes the exact itinerary,
    so it drops the user straight onto the fare. When it is missing we rebuild
    the standard Aviasales search path, which is `ORIGIN DDMM DEST [DDMM] PAX`.

    Module-level rather than a method because the site exporter needs the same
    URL for rows read back out of the database, where no provider instance is
    in play.
    """
    link = deep_link or ""
    if link.startswith("http"):
        return _with_marker(link, marker)
    if link.startswith("/"):
        return _with_marker(f"{_SEARCH_HOST}{link}", marker)

    path = origin.upper()
    if depart_date:
        path += depart_date.strftime("%d%m")
    path += destination.upper()
    if return_date:
        path += return_date.strftime("%d%m")
    return _with_marker(f"{_SEARCH_HOST}/search/{path}1", marker)


def _with_marker(url: str, marker: str) -> str:
    if not marker:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}marker={marker}"
