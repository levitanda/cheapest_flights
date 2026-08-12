"""The contract every price source has to satisfy."""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, Sequence, runtime_checkable
from urllib.parse import quote_plus

from ..models import Offer


@runtime_checkable
class PriceProvider(Protocol):
    name: str

    def city_directions(self, origin: str) -> Sequence[Offer]:
        """Cheapest known fare from `origin` to every destination it serves.

        This is the discovery sweep — one call that surfaces routes nobody
        thought to put on a watchlist, which is where the surprising deals
        actually come from.
        """

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
        """Priced itineraries for one route, optionally scoped to a month."""

    def booking_url(self, offer: Offer) -> str:
        """A human-openable link for this offer."""


def google_flights_url(
    origin: str,
    destination: str,
    depart: Optional[date],
    ret: Optional[date],
    lang: str = "iw",
) -> str:
    """Cross-check link.

    Deal-club screenshots that don't reproduce are the single most common
    complaint about services like this, so every fare carries independent
    places to verify it before booking.
    """
    query = f"Flights from {origin} to {destination}"
    if depart:
        query += f" on {depart.isoformat()}"
    if ret:
        query += f" through {ret.isoformat()}"
    return (
        "https://www.google.com/travel/flights"
        f"?q={quote_plus(query)}&curr=USD&hl={lang}&gl=IL"
    )


def skyscanner_il_url(
    origin: str,
    destination: str,
    depart: Optional[date],
    ret: Optional[date],
) -> str:
    """Israeli Skyscanner. Path segments are yymmdd; omitting the return leg
    is what makes it a one-way search."""
    parts = ["https://www.skyscanner.co.il/transport/flights",
             origin.lower(), destination.lower()]
    if depart:
        parts.append(depart.strftime("%y%m%d"))
    if ret:
        parts.append(ret.strftime("%y%m%d"))
    return "/".join(parts) + "/?adults=1&currency=USD&locale=he-IL&market=IL"


def kiwi_url(
    origin: str,
    destination: str,
    depart: Optional[date],
    ret: Optional[date],
) -> str:
    base = f"https://www.kiwi.com/en/search/results/{origin.upper()}/{destination.upper()}"
    if depart:
        base += f"/{depart.isoformat()}"
        if ret:
            base += f"/{ret.isoformat()}"
    return base


def comparison_links(
    origin: str,
    destination: str,
    depart: Optional[date],
    ret: Optional[date],
) -> list[dict]:
    """Independent places to check the same route.

    These are *searches*, not the fare we found — only the provider's own
    booking link carries the price we are quoting. The UI has to say so;
    presenting a search as "buy it here for $62" is exactly the complaint that
    made the off-the-shelf deal clubs untrustworthy.
    """
    return [
        {"id": "skyscanner", "url": skyscanner_il_url(origin, destination, depart, ret)},
        {"id": "google", "url": google_flights_url(origin, destination, depart, ret)},
        {"id": "kiwi", "url": kiwi_url(origin, destination, depart, ret)},
    ]
