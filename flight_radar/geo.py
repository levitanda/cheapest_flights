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
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

_OVERRIDES_DIR = Path(__file__).with_name("data")


def _load_overrides() -> dict[str, dict[str, str]]:
    """Read `data/cities_<lang>.json` files shipped with the package."""
    out: dict[str, dict[str, str]] = {}
    if not _OVERRIDES_DIR.is_dir():
        return out
    for path in sorted(_OVERRIDES_DIR.glob("cities_*.json")):
        lang = path.stem.split("_", 1)[1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("geo: bad override file %s: %s", path.name, exc)
            continue
        if isinstance(payload, dict):
            # Underscore keys carry documentation, not airports.
            out[lang] = {
                str(k).upper(): str(v)
                for k, v in payload.items()
                if not str(k).startswith("_")
            }
    return out

_DUMP_URL = "https://api.travelpayouts.com/data/{lang}/{name}.json"

# The site leads in Hebrew for an Israeli audience, with Russian and English
# behind a switcher. Names are resolved in all three at publish time so the
# page never has to fetch a translation.
DEFAULT_LANG = "he"
SITE_LANGS = ("he", "ru", "en")

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
        lang: str = DEFAULT_LANG,
        langs: Optional[Sequence[str]] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.lang = lang
        # The site offers three languages, so every name is resolved in all of
        # them once and shipped together — the page must not have to call back
        # for a translation when the reader flips the switcher.
        self.langs = tuple(langs) if langs else (lang,)
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
        # Cities first, then airports. Airport rows refine the coordinates —
        # they are the precise ones for distance — but must NOT take over the
        # display name: for a code like ATH the airport row reads "Eleftherios
        # Venizelos International Airport" where the city row reads "Афины",
        # and the second is what belongs on a page of flight deals.
        for lang in self.langs:
            for source in ("cities", "airports"):
                # Cache filenames carry the language. Without that, switching
                # language would keep serving the previously cached dump
                # forever, because the cache is keyed by filename alone.
                filename = f"{source}.{lang}.json"
                url = _DUMP_URL.format(lang=lang, name=source)
                try:
                    payload = self._cached(filename, url)
                except Exception as exc:
                    logger.warning("geo: failed to load %s/%s: %s", lang, source, exc)
                    continue
                self._absorb(payload, lang, is_airport=source == "airports")

        self._apply_overrides()
        self._loaded = True
        logger.info(
            "geo: %d points loaded for %s", len(self._points), ",".join(self.langs)
        )

    def _absorb(self, payload: object, lang: str, is_airport: bool) -> None:
        for entry in payload if isinstance(payload, list) else []:
            code = (entry.get("code") or "").upper()
            coords = entry.get("coordinates") or {}
            lat, lon = coords.get("lat"), coords.get("lon")
            if not code or lat is None or lon is None:
                continue

            point = self._points.setdefault(
                code,
                {"lat": float(lat), "lon": float(lon), "names": {}, "country": ""},
            )
            if is_airport:
                # Airport coordinates are the precise ones for distance.
                point["lat"] = float(lat)
                point["lon"] = float(lon)
            point["country"] = point["country"] or (entry.get("country_code") or "")

            name = entry.get("name")
            translations = entry.get("name_translations") or {}
            resolved = translations.get(lang) or name
            # City names win: the airport row for ATH reads "Eleftherios
            # Venizelos International Airport" where the city row reads
            # "אתונה", and the latter belongs on a page of flight deals.
            if resolved and (not is_airport or lang not in point["names"]):
                point["names"][lang] = resolved

    def _apply_overrides(self) -> None:
        """Overlay hand-checked names where the upstream dump has none.

        Travelpayouts does not publish a Hebrew dump, so Hebrew would
        otherwise fall back to English on every card — on a site whose whole
        point is to be Israeli.
        """
        overrides = _load_overrides()
        for lang, mapping in overrides.items():
            for code, value in mapping.items():
                point = self._points.get(code.upper())
                if point:
                    point["names"][lang] = value
                else:
                    # Keep the name even for a code the dumps do not carry;
                    # coordinates stay unknown, which only disables distance.
                    self._points[code.upper()] = {
                        "lat": None, "lon": None,
                        "names": {lang: value}, "country": "",
                    }

    # -- lookups ------------------------------------------------------------

    def coords(self, iata: str) -> Optional[tuple[float, float]]:
        self.load()
        point = self._points.get(iata.upper())
        if not point or point.get("lat") is None:
            return None
        return (point["lat"], point["lon"])

    def name(self, iata: str, lang: Optional[str] = None) -> str:
        """Best available name, degrading language by language to the code."""
        self.load()
        code = iata.upper()
        point = self._points.get(code)
        if not point:
            return code
        names = point["names"]
        # English before the other site languages: a Russian reader missing a
        # Russian name is better served "Athens" than "אתונה", and vice versa.
        for candidate in (lang or self.lang, "en", *self.langs):
            if names.get(candidate):
                return names[candidate]
        return next(iter(names.values()), code)

    def names(self, iata: str) -> dict[str, str]:
        """Every language at once, for shipping to a multilingual page."""
        self.load()
        code = iata.upper()
        point = self._points.get(code)
        if not point:
            return {lang: code for lang in self.langs}
        return {lang: self.name(code, lang) for lang in self.langs}

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
