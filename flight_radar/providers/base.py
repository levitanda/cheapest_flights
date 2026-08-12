"""The contract every price source has to satisfy."""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, Sequence, runtime_checkable

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
) -> str:
    """Cross-check link.

    Deal-club screenshots that don't reproduce are the single most common
    complaint about services like this, so every alert carries a second,
    independent place to verify the fare before booking.
    """
    query = f"Flights from {origin} to {destination}"
    if depart:
        query += f" on {depart.isoformat()}"
    if ret:
        query += f" through {ret.isoformat()}"
    from urllib.parse import quote_plus

    return f"https://www.google.com/travel/flights?q={quote_plus(query)}"
