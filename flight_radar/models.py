"""Value objects passed between the provider, detector and notifier layers.

Everything downstream of a provider speaks `Offer`, so adding a second data
source (Amadeus, a scraper, a manual CSV) means writing one adapter and
touching nothing else.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

# A round-trip $300 fare and a one-way $300 fare are not the same event, so
# baselines are kept in separate buckets and never compared to each other.
TRIP_ROUND = "rt"
TRIP_ONE_WAY = "ow"

TIER_GOOD = "good"
TIER_GREAT = "great"
TIER_EXCEPTIONAL = "exceptional"
TIER_ERROR_FARE = "error_fare"

# Ordered weakest to strongest; used for sorting and for "is this louder than
# what we already sent" comparisons.
TIER_ORDER = (TIER_GOOD, TIER_GREAT, TIER_EXCEPTIONAL, TIER_ERROR_FARE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Offer:
    """One priced itinerary as reported by a provider at a point in time."""

    origin: str
    destination: str
    price: float
    currency: str
    depart_date: Optional[date] = None
    return_date: Optional[date] = None
    transfers: Optional[int] = None
    airline: Optional[str] = None
    deep_link: Optional[str] = None
    # Which agency actually sells this fare. Aviasales is a metasearch across
    # hundreds of sellers, so "where the price was found" is a real answer we
    # can surface rather than a generic search link.
    seller: Optional[str] = None
    source: str = "unknown"
    observed_at: datetime = field(default_factory=_utcnow)

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def trip_kind(self) -> str:
        return TRIP_ROUND if self.return_date else TRIP_ONE_WAY

    @property
    def trip_nights(self) -> Optional[int]:
        if self.depart_date and self.return_date:
            return (self.return_date - self.depart_date).days
        return None

    @property
    def depart_month(self) -> Optional[str]:
        return self.depart_date.strftime("%Y-%m") if self.depart_date else None

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", self.origin.upper())
        object.__setattr__(self, "destination", self.destination.upper())
        object.__setattr__(self, "currency", self.currency.lower())


@dataclass(frozen=True, slots=True)
class Baseline:
    """What this route normally costs, summarised robustly.

    Median and MAD rather than mean and standard deviation on purpose: the
    whole point is to find outliers, and outliers wreck a mean. A single $19
    error fare in the window would drag a mean down far enough to hide the
    next one.
    """

    route: str
    trip_kind: str
    currency: str
    median: float
    mad: float
    p10: float
    sample_size: int
    distinct_days: int

    @property
    def robust_sigma(self) -> float:
        """MAD rescaled to be comparable to a standard deviation.

        Floored at 5% of the median because a route observed at a flat price
        all week has MAD == 0, and a zero sigma would score every fare a
        cent below it as infinitely anomalous.
        """
        sigma = 1.4826 * self.mad
        return max(sigma, 0.05 * self.median)


@dataclass(frozen=True, slots=True)
class Deal:
    """An offer the detector judged abnormal, with the evidence behind it."""

    offer: Offer
    baseline_price: float
    drop_pct: float
    z_score: float
    tier: str
    basis: str  # "history" or "heuristic"
    reason: str

    @property
    def savings(self) -> float:
        return max(0.0, self.baseline_price - self.offer.price)

    @property
    def rank(self) -> tuple[int, float]:
        """Sort key: loudest tier first, then deepest discount."""
        return (TIER_ORDER.index(self.tier), self.drop_pct)

    @property
    def fingerprint(self) -> str:
        """Identity of the *deal*, not of the offer.

        Price is bucketed to 5% steps and the date to its month so that the
        same fare re-reported with trivial noise (a $4 wobble, a neighbouring
        departure date) collapses onto one fingerprint instead of paging the
        user twice. The bucket is multiplicative — a $20 step matters on a $60
        fare and is noise on a $900 one.
        """
        bucket = int(math.log(max(self.offer.price, 1.0)) / math.log(1.05))
        parts = (
            self.offer.origin,
            self.offer.destination,
            self.offer.trip_kind,
            self.offer.depart_month or "any",
            str(bucket),
        )
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
