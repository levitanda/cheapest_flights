from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from flight_radar.models import Deal
from flight_radar.storage import _percentile

from .conftest import make_offer, seed_history


class TestPercentile:
    def test_interpolates_between_neighbours(self):
        assert _percentile([10, 20, 30, 40], 0.5) == pytest.approx(25.0)

    def test_edges(self):
        values = [10, 20, 30, 40]
        assert _percentile(values, 0.0) == 10
        assert _percentile(values, 1.0) == 40

    def test_single_value(self):
        assert _percentile([7], 0.9) == 7

    def test_empty_is_an_error(self):
        with pytest.raises(ValueError):
            _percentile([], 0.5)


class TestBaseline:
    def test_no_history_returns_none(self, storage):
        assert storage.baseline("TLV", "ATH", "rt", "usd", 90) is None

    def test_summarises_history(self, storage):
        seed_history(storage, [100, 200, 300])
        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)

        assert baseline.median == 200
        assert baseline.sample_size == 3
        assert baseline.distinct_days == 3

    def test_outlier_does_not_move_the_median(self, storage):
        """The property the whole detector depends on."""
        seed_history(storage, [200, 205, 195, 210, 190, 19])
        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)
        assert baseline.median == pytest.approx(197.5)

    def test_window_excludes_stale_observations(self, storage):
        old = datetime.now(timezone.utc) - timedelta(days=200)
        storage.record_offers([make_offer(price=999, observed_at=old)])
        seed_history(storage, [100, 110, 105])

        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)
        assert baseline.sample_size == 3
        assert baseline.median == 105

    def test_trip_kinds_are_separate_buckets(self, storage):
        seed_history(storage, [400, 410, 420])
        storage.record_offers([make_offer(price=150, ret=None)])

        round_trip = storage.baseline("TLV", "ATH", "rt", "usd", 90)
        one_way = storage.baseline("TLV", "ATH", "ow", "usd", 90)

        assert round_trip.sample_size == 3
        assert one_way.sample_size == 1
        assert one_way.median == 150

    def test_currencies_are_separate_buckets(self, storage):
        seed_history(storage, [100, 110, 120])
        storage.record_offers([make_offer(price=4000, currency="ils")])

        assert storage.baseline("TLV", "ATH", "rt", "usd", 90).sample_size == 3
        assert storage.baseline("TLV", "ATH", "rt", "ils", 90).sample_size == 1

    def test_robust_sigma_is_floored_on_flat_history(self, storage):
        """A route seen at exactly one price has MAD 0; sigma must not be 0."""
        seed_history(storage, [200] * 12)
        baseline = storage.baseline("TLV", "ATH", "rt", "usd", 90)

        assert baseline.mad == 0
        assert baseline.robust_sigma == pytest.approx(10.0)


class TestWrites:
    def test_zero_priced_offers_are_dropped(self, storage):
        written = storage.record_offers([make_offer(price=0), make_offer(price=100)])
        assert written == 1

    def test_prune_removes_only_old_rows(self, storage):
        old = datetime.now(timezone.utc) - timedelta(days=400)
        storage.record_offers([make_offer(price=100, observed_at=old)])
        seed_history(storage, [200])

        assert storage.prune(365) == 1
        assert storage.stats()["observations"] == 1


class TestAlertLog:
    def _deal(self, price: float = 95.0) -> Deal:
        return Deal(
            offer=make_offer(price=price),
            baseline_price=200.0,
            drop_pct=0.5,
            z_score=3.0,
            tier="great",
            basis="history",
            reason="test",
        )

    def test_fingerprint_roundtrip(self, storage):
        deal = self._deal()
        assert storage.seen_fingerprint(deal.fingerprint) is False
        storage.record_alert(deal)
        assert storage.seen_fingerprint(deal.fingerprint) is True

    def test_recording_twice_is_idempotent(self, storage):
        deal = self._deal()
        storage.record_alert(deal)
        storage.record_alert(deal)
        assert storage.stats()["alerts"] == 1

    def test_last_alert_price_returns_the_cheapest_in_window(self, storage):
        storage.record_alert(self._deal(price=150))
        storage.record_alert(self._deal(price=90))
        storage.record_alert(self._deal(price=120))

        best = storage.last_alert_price("TLV", "ATH", "rt", "2026-09", 48)
        assert best == 90

    def test_last_alert_price_ignores_other_months(self, storage):
        storage.record_alert(self._deal())
        assert storage.last_alert_price("TLV", "ATH", "rt", "2027-01", 48) is None

    def test_prices_outside_the_cooldown_do_not_count(self, storage):
        storage.record_alert(self._deal())
        assert storage.last_alert_price("TLV", "ATH", "rt", "2026-09", 0) is None
