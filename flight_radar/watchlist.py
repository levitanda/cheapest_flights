"""What to scan, loaded from `watchlist.toml`.

Two modes, and the difference matters:

  discover — one cheap call listing the cheapest fare from an airport to every
             destination it serves. This is the mode that finds trips you
             weren't looking for, which is most of the value.
  track    — month-by-month drill-down on a route you actually care about.
             Costs one call per month scanned, but builds the dense history
             the statistical detector needs.

A sensible TLV-only default is used when the file is absent, so the service
runs correctly with no configuration at all.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from .models import Offer

logger = logging.getLogger(__name__)

MODE_DISCOVER = "discover"
MODE_TRACK = "track"
# Broader than `discover`: one call, but the raw recent finds rather than only
# the destinations with a cached cheapest fare. `discover` from Tel Aviv
# returned 29 destinations and no Amsterdam.
MODE_LATEST = "latest"
MODES = (MODE_DISCOVER, MODE_TRACK, MODE_LATEST)


@dataclass(frozen=True, slots=True)
class WatchEntry:
    origin: str
    destination: Optional[str] = None
    mode: str = MODE_DISCOVER
    months_ahead: int = 4
    direct_only: bool = False
    min_nights: Optional[int] = None
    max_nights: Optional[int] = None
    max_price: Optional[float] = None
    exclude: frozenset[str] = field(default_factory=frozenset)
    include_countries: frozenset[str] = field(default_factory=frozenset)

    def accepts(self, offer: Offer, country: str = "") -> bool:
        """Post-filter applied to everything a provider returns."""
        if offer.destination in self.exclude:
            return False
        if self.include_countries and country.upper() not in self.include_countries:
            return False
        if self.max_price is not None and offer.price > self.max_price:
            return False
        nights = offer.trip_nights
        # A one-way has no trip length, so length filters simply don't apply.
        if nights is not None:
            if self.min_nights is not None and nights < self.min_nights:
                return False
            if self.max_nights is not None and nights > self.max_nights:
                return False
        if self.direct_only and offer.transfers not in (None, 0):
            return False
        return True

    def months(self, today: Optional[date] = None) -> list[str]:
        """The YYYY-MM strings a `track` entry should request."""
        today = today or date.today()
        out = []
        year, month = today.year, today.month
        for _ in range(max(1, self.months_ahead)):
            out.append(f"{year:04d}-{month:02d}")
            month += 1
            if month > 12:
                month = 1
                year += 1
        return out


DEFAULT_WATCHLIST = (
    WatchEntry(origin="TLV", mode=MODE_DISCOVER),
)


def _entry_from_dict(raw: dict, defaults: dict) -> Optional[WatchEntry]:
    merged = {**defaults, **raw}
    origin = str(merged.get("origin", "")).upper().strip()
    if not origin:
        logger.warning("watchlist entry without an origin skipped: %r", raw)
        return None

    destination = merged.get("destination")
    mode = str(merged.get("mode") or (MODE_TRACK if destination else MODE_DISCOVER)).lower()
    if mode not in MODES:
        logger.warning("unknown mode %r for %s, treating as discover", mode, origin)
        mode = MODE_DISCOVER
    if mode == MODE_TRACK and not destination:
        logger.warning("track entry for %s has no destination, skipped", origin)
        return None

    def _opt_int(key: str) -> Optional[int]:
        value = merged.get(key)
        return int(value) if value is not None else None

    def _opt_float(key: str) -> Optional[float]:
        value = merged.get(key)
        return float(value) if value is not None else None

    return WatchEntry(
        origin=origin,
        destination=str(destination).upper() if destination else None,
        mode=mode,
        months_ahead=int(merged.get("months_ahead", 4)),
        direct_only=bool(merged.get("direct_only", False)),
        min_nights=_opt_int("min_nights"),
        max_nights=_opt_int("max_nights"),
        max_price=_opt_float("max_price"),
        exclude=frozenset(str(c).upper() for c in merged.get("exclude", ())),
        include_countries=frozenset(
            str(c).upper() for c in merged.get("include_countries", ())
        ),
    )


def load(path: Path | str) -> Sequence[WatchEntry]:
    path = Path(path)
    if not path.exists():
        logger.info("no watchlist at %s, using the default TLV sweep", path)
        return DEFAULT_WATCHLIST

    with path.open("rb") as fh:
        payload = tomllib.load(fh)

    defaults = payload.get("defaults") or {}
    entries = [
        entry
        for raw in payload.get("watch", [])
        if isinstance(raw, dict) and (entry := _entry_from_dict(raw, defaults)) is not None
    ]
    if not entries:
        logger.warning("watchlist at %s has no usable entries, using default", path)
        return DEFAULT_WATCHLIST
    return entries
