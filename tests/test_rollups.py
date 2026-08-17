"""Aggregates that make a year of history affordable.

Raw observations arrive at ~4,800 rows a day and the whole database is moved
through S3 on every invocation, so keeping a year of them would mean shipping
hundreds of megabytes eight times daily. These rollups are what the charts and
the detector read instead.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from .conftest import make_offer, seed_history


def days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


class TestDailyRollup:
    def test_one_row_per_route_per_day(self, storage):
        storage.record_offers([
            make_offer(price=200, observed_at=days_ago(1)),
            make_offer(price=150, observed_at=days_ago(1)),
            make_offer(price=180, observed_at=days_ago(0)),
        ])
        rows = storage._conn.execute(
            "SELECT day, min_price, observations FROM daily_price ORDER BY day"
        ).fetchall()

        assert len(rows) == 2
        assert rows[0]["min_price"] == 150      # cheapest of that day, not the last
        assert rows[0]["observations"] == 2

    def test_rollup_is_rebuilt_not_appended(self, storage):
        """Recording twice must not double the count for a day."""
        offers = [make_offer(price=200, observed_at=days_ago(1))]
        storage.record_offers(offers)
        storage.record_offers(offers)

        row = storage._conn.execute(
            "SELECT observations FROM daily_price").fetchone()
        assert row["observations"] == 2      # two rows exist, counted once

    def test_trip_kinds_stay_separate(self, storage):
        storage.record_offers([
            make_offer(price=400, observed_at=days_ago(1)),
            make_offer(price=150, ret=None, observed_at=days_ago(1)),
        ])
        kinds = {
            r["trip_kind"]: r["min_price"]
            for r in storage._conn.execute("SELECT trip_kind, min_price FROM daily_price")
        }
        assert kinds == {"rt": 400.0, "ow": 150.0}


class TestBaselineFromRollup:
    def test_baseline_is_the_typical_cheapest_day(self, storage):
        # Each day: one cheap fare and one dear one. The baseline should track
        # the cheap ones — that is what a reader compares against.
        for day, (cheap, dear) in enumerate([(100, 500), (110, 520), (105, 480)]):
            storage.record_offers([
                make_offer(price=cheap, observed_at=days_ago(day)),
                make_offer(price=dear, observed_at=days_ago(day)),
            ])
        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)

        assert baseline.median == pytest.approx(105)
        assert baseline.distinct_days == 3
        assert baseline.sample_size == 6      # raw rows behind the rollup

    def test_reliability_gates_still_count_raw_observations(self, storage):
        """One row per day must not silently redefine MIN_OBSERVATIONS."""
        seed_history(storage, [200] * 12)
        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)

        assert baseline.sample_size == 12
        assert baseline.distinct_days == 10

    def test_window_excludes_old_days(self, storage):
        storage.record_offers([make_offer(price=99, observed_at=days_ago(120))])
        storage.record_offers([make_offer(price=200, observed_at=days_ago(1))])

        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)
        assert baseline.median == 200


class TestMonthRollup:
    def test_cheapest_per_departure_month(self, storage):
        storage.record_offers([
            make_offer(price=300, depart=date(2026, 10, 5), ret=date(2026, 10, 12)),
            make_offer(price=180, depart=date(2026, 10, 20), ret=date(2026, 10, 27)),
            make_offer(price=250, depart=date(2026, 11, 3), ret=date(2026, 11, 10)),
        ])
        rows = {
            r["depart_month"]: r["min_price"]
            for r in storage._conn.execute("SELECT depart_month, min_price FROM month_price")
        }
        assert rows == {"2026-10": 180.0, "2026-11": 250.0}

    def test_rebuilt_so_departed_months_disappear(self, storage):
        """It answers 'when can I fly', not 'what was once on offer'."""
        storage.record_offers([make_offer(price=180, depart=date(2026, 10, 5))])
        assert storage._conn.execute("SELECT COUNT(*) c FROM month_price").fetchone()["c"] == 1

        storage._conn.execute("DELETE FROM observations")
        storage.record_offers([make_offer(price=250, depart=date(2026, 12, 1))])

        months = [r["depart_month"] for r in
                  storage._conn.execute("SELECT depart_month FROM month_price")]
        assert months == ["2026-12"]

    def test_month_fares_are_ordered_cheapest_first(self, storage):
        storage.record_offers([
            make_offer(destination="BKK", price=600, depart=date(2026, 10, 5)),
            make_offer(destination="ATH", price=120, depart=date(2026, 10, 5)),
        ])
        rows = storage.month_fares()
        assert [r["destination"] for r in rows] == ["ATH", "BKK"]

    def test_month_fare_carries_the_real_dates_of_that_fare(self, storage):
        storage.record_offers([
            make_offer(price=180, depart=date(2026, 10, 20), ret=date(2026, 10, 27)),
            make_offer(price=300, depart=date(2026, 10, 5), ret=date(2026, 10, 12)),
        ])
        row = storage.month_fares()[0]
        assert row["min_price"] == 180
        assert row["depart_date"] == "2026-10-20"


class TestRetention:
    def test_raw_is_pruned_but_the_rollup_survives(self, storage):
        """The whole point: history outlives the rows that produced it."""
        storage.record_offers([make_offer(price=200, observed_at=days_ago(30))])
        assert storage.stats()["observations"] == 1

        storage.prune(keep_days=7, keep_rollup_days=400)

        assert storage.stats()["observations"] == 0
        rows = storage._conn.execute("SELECT COUNT(*) c FROM daily_price").fetchone()
        assert rows["c"] == 1

    def test_rollup_is_pruned_at_its_own_horizon(self, storage):
        storage.record_offers([make_offer(price=200, observed_at=days_ago(500))])
        storage.prune(keep_days=7, keep_rollup_days=400)
        assert storage._conn.execute(
            "SELECT COUNT(*) c FROM daily_price").fetchone()["c"] == 0

    def test_baseline_survives_pruning_of_raw(self, storage):
        for day in range(10, 40):
            storage.record_offers([make_offer(price=200 + day, observed_at=days_ago(day))])
        storage.prune(keep_days=7, keep_rollup_days=400)

        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)
        assert baseline is not None
        assert baseline.distinct_days == 30


class TestHistorySeries:
    def test_series_is_ordered_and_scoped_to_requested_routes(self, storage):
        for day in range(3):
            storage.record_offers([
                make_offer(price=100 + day, observed_at=days_ago(day)),
                make_offer(destination="BKK", price=500, observed_at=days_ago(day)),
            ])
        series = storage.price_history([("TLV", "ATH", "rt")])

        assert list(series) == [("TLV", "ATH", "rt")]
        days = [r["day"] for r in series[("TLV", "ATH", "rt")]]
        assert days == sorted(days)

    def test_no_routes_requested_is_not_a_full_scan(self, storage):
        seed_history(storage, [100, 200])
        assert storage.price_history([]) == {}
