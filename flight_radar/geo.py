"""Airport metadata and the distance-based price expectation.

This exists to solve the cold-start problem. On day one there is no price
history, so the statistical detector has nothing to compare against and would
stay silent for weeks. A rough "what should a flight this far realistically
cost" curve is enough to catch the obvious outliers immediately, and the
detector stops relying on it per-route as soon as real history accumulates.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_AIRPORTS_URL = "https://api.travelpayouts.com/data/en/airports.json"
_CITIES_URL = "https://api.travelpayouts.com/data/en/cities.json"

# The reference tables change a few times a year at most.
_CACHE_TTL_SECONDS = 30 * 24 * 3600

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


# Piecewise linear round-trip economy fare in USD. Per-km cost falls with
# distance — short hops carry fixed airport and handling costs that a long
# haul amortises. Calibrated loosely against typical TLV fares; it only has to
# be right to within a factor of ~1.5 for the cold-start test to be useful.
_FARE_BREAKPOINTS = ((1500.0, 0.075), (5000.0, 0.055), (float("inf"), 0.045))
_FARE_BASE_USD = 40.0


def expected_round_trip_usd(distance_km: float) -> float:
    """Rough 'normal' round-trip price for a given great-circle distance."""
    total = _FARE_BASE_USD
    remaining = max(0.0, distance_km)
    previous = 0.0
    for limit, rate in _FARE_BREAKPOINTS:
        span = min(remaining, limit - previous)
        if span <= 0:
            break
        total += span * rate
        remaining -= span
        previous = limit
        if remaining <= 0:
            break
    return total


class Geo:
    """IATA code -> coordinates, name and country, with an on-disk cache."""

    def __init__(
        self,
        cache_dir: Path,
        fetch: Optional[Callable[[str], list | dict]] = None,
        ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._fetch = fetch or self._http_fetch
        self._points: dict[str, dict] = {}
        self._loaded = False

    # -- loading ------------------------------------------------------------

    @staticmethod
    def _http_fetch(url: str) -> list | dict:
        import requests

        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _cached(self, name: str, url: str) -> list | dict:
        path = self.cache_dir / name
        if path.exists() and (time.time() - path.stat().st_mtime) < self.ttl_seconds:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("geo cache %s unreadable (%s), refetching", name, exc)
        payload = self._fetch(url)
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:  # a read-only volume shouldn't be fatal
            logger.warning("could not write geo cache %s: %s", name, exc)
        return payload

    def load(self) -> None:
        """Populate the lookup table. Safe to call repeatedly."""
        if self._loaded:
            return
        # Cities are loaded first so airport entries win on code collisions:
        # for a metro code like TLV both files have a row, and the airport
        # coordinates are the ones that matter for distance.
        for name, url in (("cities.json", _CITIES_URL), ("airports.json", _AIRPORTS_URL)):
            try:
                payload = self._cached(name, url)
            except Exception as exc:
                logger.warning("geo: failed to load %s: %s", name, exc)
                continue
            for entry in payload if isinstance(payload, list) else []:
                code = (entry.get("code") or "").upper()
                coords = entry.get("coordinates") or {}
                lat, lon = coords.get("lat"), coords.get("lon")
                if not code or lat is None or lon is None:
                    continue
                self._points[code] = {
                    "lat": float(lat),
                    "lon": float(lon),
                    "name": entry.get("name") or code,
                    "translations": entry.get("name_translations") or {},
                    "country": entry.get("country_code") or "",
                }
        self._loaded = True
        logger.info("geo: %d points loaded", len(self._points))

    # -- lookups ------------------------------------------------------------

    def coords(self, iata: str) -> Optional[tuple[float, float]]:
        self.load()
        point = self._points.get(iata.upper())
        return (point["lat"], point["lon"]) if point else None

    def name(self, iata: str, lang: str = "ru") -> str:
        self.load()
        point = self._points.get(iata.upper())
        if not point:
            return iata.upper()
        return point["translations"].get(lang) or point["name"]

    def country(self, iata: str) -> str:
        self.load()
        point = self._points.get(iata.upper())
        return point["country"] if point else ""

    def distance_km(self, origin: str, destination: str) -> Optional[float]:
        a, b = self.coords(origin), self.coords(destination)
        if not a or not b:
            return None
        return haversine_km(a[0], a[1], b[0], b[1])

    def expected_price(self, origin: str, destination: str, one_way: bool) -> Optional[float]:
        """Expected fare in USD, or None when either endpoint is unknown."""
        km = self.distance_km(origin, destination)
        if km is None:
            return None
        price = expected_round_trip_usd(km)
        # One-ways are rarely half of a return; two thirds is the closer rule.
        return price * 0.66 if one_way else price
