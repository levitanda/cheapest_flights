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
        data_dir=tmp_path,
        keep_history_days=365,
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


@pytest.fixture
def geo(tmp_path: Path) -> Geo:
    """Geo backed by a fixed in-memory table — no network, stable distances."""
    airports = [
        {
            "code": "TLV",
            "name": "Ben Gurion",
            "coordinates": {"lat": 32.0114, "lon": 34.8867},
            "country_code": "IL",
            "name_translations": {"ru": "Тель-Авив"},
        },
        {
            "code": "ATH",
            "name": "Athens",
            "coordinates": {"lat": 37.9364, "lon": 23.9445},
            "country_code": "GR",
            "name_translations": {"ru": "Афины"},
        },
        {
            "code": "BKK",
            "name": "Suvarnabhumi",
            "coordinates": {"lat": 13.6900, "lon": 100.7501},
            "country_code": "TH",
            "name_translations": {"ru": "Бангкок"},
        },
        {
            "code": "JFK",
            "name": "John F Kennedy",
            "coordinates": {"lat": 40.6413, "lon": -73.7781},
            "country_code": "US",
            "name_translations": {"ru": "Нью-Йорк"},
        },
    ]

    def fake_fetch(url: str):
        return airports if "airports" in url else []

    return Geo(tmp_path / "cache", fetch=fake_fetch)


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
