from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from flight_radar.config import Settings
from flight_radar.geo import Geo
from flight_radar.models import Offer
from flight_radar.storage import Storage


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        tp_token="test-token",
        tp_marker="12345",
        currency="usd",
        usd_rate=1.0,
        http_timeout=5,
        market="il",
        enrich_limit=30,
        data_dir=tmp_path,
        keep_history_days=7,
        keep_rollup_days=400,
        baseline_window_days=90,
        min_observations=12,
        min_distinct_days=6,
        min_drop_pct=0.35,
        min_z_score=3.0,
        cold_start_ratio=0.45,
        error_fare_drop_pct=0.70,
        alert_cooldown_hours=48,
        alert_improve_pct=0.15,
        max_alerts_per_scan=6,
        scan_interval_minutes=180,
        site_bucket="",
        site_data_key="data/deals.json",
        state_bucket="",
        state_prefix="state",
        telegram_token="",
        telegram_chat_id="",
        pushover_token="",
        pushover_user="",
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    store = Storage(tmp_path / "test.sqlite3")
    yield store
    store.close()


# Coordinates are the real ones so distance-based assertions stay meaningful.
_PLACES = {
    "TLV": ((32.0114, 34.8867), "IL", {"en": "Tel Aviv", "ru": "Тель-Авив"}),
    "ATH": ((37.9364, 23.9445), "GR", {"en": "Athens", "ru": "Афины"}),
    "BKK": ((13.6900, 100.7501), "TH", {"en": "Bangkok", "ru": "Бангкок"}),
    "JFK": ((40.6413, -73.7781), "US", {"en": "New York", "ru": "Нью-Йорк"}),
    "LCA": ((34.8751, 33.6249), "CY", {"en": "Larnaca", "ru": "Ларнака"}),
}


@pytest.fixture
def geo(tmp_path: Path) -> Geo:
    """Geo backed by a fixed in-memory table — no network, stable distances.

    Hebrew is deliberately absent from the fake dumps: upstream publishes no
    Hebrew, so tests exercise the same override path production relies on.
    """

    def fake_fetch(url: str):
        if "cities" not in url:
            return []
        lang = "ru" if "/ru/" in url else "en"
        return [
            {
                "code": code,
                "name": names.get("en", code),
                "coordinates": {"lat": coords[0], "lon": coords[1]},
                "country_code": country,
                "name_translations": {lang: names.get(lang, names["en"])},
            }
            for code, (coords, country, names) in _PLACES.items()
        ]

    from flight_radar.geo import SITE_LANGS

    return Geo(tmp_path / "cache", fetch=fake_fetch, langs=SITE_LANGS)


# `ret=None` has to mean "one-way", which a None default would swallow.
_UNSET = object()


def make_offer(
    origin: str = "TLV",
    destination: str = "ATH",
    price: float = 200.0,
    currency: str = "usd",
    depart: date | None = None,
    ret: date | None = _UNSET,
    observed_at: datetime | None = None,
    **kwargs,
) -> Offer:
    depart = depart or date(2026, 9, 10)
    ret = date(2026, 9, 17) if ret is _UNSET else ret
    return Offer(
        origin=origin,
        destination=destination,
        price=price,
        currency=currency,
        depart_date=depart,
        return_date=ret,
        observed_at=observed_at or datetime.now(timezone.utc),
        source="test",
        **kwargs,
    )


def seed_history(
    storage: Storage,
    prices: list[float],
    origin: str = "TLV",
    destination: str = "ATH",
    spread_days: int = 10,
) -> None:
    """Write observations spread across distinct days.

    The detector refuses to trust history gathered in a single burst, so tests
    that want a usable baseline have to spread it out the same way reality
    would.
    """
    now = datetime.now(timezone.utc)
    offers = [
        make_offer(
            origin=origin,
            destination=destination,
            price=price,
            observed_at=now - timedelta(days=index % spread_days, hours=index),
        )
        for index, price in enumerate(prices)
    ]
    storage.record_offers(offers)
