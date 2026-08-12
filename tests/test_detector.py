from __future__ import annotations

from datetime import date

import pytest

from flight_radar.detector import Detector
from flight_radar.models import (
    TIER_ERROR_FARE,
    TIER_EXCEPTIONAL,
    TIER_GREAT,
    Offer,
)

from .conftest import make_offer, seed_history


class TestStatisticalPath:
    def test_normal_price_on_known_route_is_silent(self, settings, storage, geo):
        seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
        detector = Detector(settings, storage, geo)
        assert detector.evaluate(make_offer(price=205)) is None

    def test_deep_drop_on_stable_route_fires(self, settings, storage, geo):
        seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
        detector = Detector(settings, storage, geo)
        deal = detector.evaluate(make_offer(price=95))

        assert deal is not None
        assert deal.basis == "history"
        assert deal.drop_pct == pytest.approx(0.535, abs=0.02)
        assert deal.tier in (TIER_GREAT, TIER_EXCEPTIONAL)

    def test_volatile_route_needs_a_bigger_drop(self, settings, storage, geo):
        """The same 40% discount should page on a stable route and stay quiet
        on one that swings that much every week."""
        volatile = [100, 300, 120, 280, 150, 320, 110, 290, 130, 310, 140, 270]
        seed_history(storage, volatile, destination="BKK")
        detector = Detector(settings, storage, geo)

        # Median of the volatile set is ~200; 120 is a 40% drop but well
        # inside the route's normal swing.
        assert detector.evaluate(make_offer(destination="BKK", price=120)) is None

    def test_price_above_p10_is_rejected(self, settings, storage, geo):
        # Mostly expensive with a few cheap outliers, so p10 sits low: a fare
        # that clears the drop threshold but is not near the bottom of what we
        # have already seen is not news.
        seed_history(storage, [90, 95, 400, 410, 420, 405, 415, 395, 425, 430, 408, 412])
        detector = Detector(settings, storage, geo)
        assert detector.evaluate(make_offer(price=250)) is None

    def test_error_fare_tier_for_extreme_drop(self, settings, storage, geo):
        seed_history(storage, [500, 520, 495, 510, 505, 515, 490, 500, 508, 512, 498, 503])
        detector = Detector(settings, storage, geo)
        deal = detector.evaluate(make_offer(price=60))

        assert deal is not None
        assert deal.tier == TIER_ERROR_FARE

    def test_one_way_is_not_judged_against_round_trip_history(self, settings, storage, geo):
        """A $150 one-way must not look like a bargain just because return
        flights on the same route average $400."""
        seed_history(storage, [400, 410, 395, 405, 420, 390, 415, 400, 405, 398, 412, 407])
        detector = Detector(settings, storage, geo)

        one_way = make_offer(price=150, ret=None)
        deal = detector.evaluate(one_way)

        # No one-way history exists, so it can only fall through to the
        # heuristic, never to the round-trip median.
        assert deal is None or deal.basis == "heuristic"


class TestHeuristicPath:
    def test_absurdly_cheap_longhaul_fires_without_history(self, settings, storage, geo):
        detector = Detector(settings, storage, geo)
        deal = detector.evaluate(make_offer(destination="BKK", price=90))

        assert deal is not None
        assert deal.basis == "heuristic"
        assert deal.z_score == 0.0

    def test_plausible_price_without_history_is_silent(self, settings, storage, geo):
        detector = Detector(settings, storage, geo)
        assert detector.evaluate(make_offer(destination="BKK", price=600)) is None

    def test_unknown_airport_cannot_be_judged(self, settings, storage, geo):
        detector = Detector(settings, storage, geo)
        assert detector.evaluate(make_offer(destination="ZZZ", price=5)) is None

    def test_no_geo_means_no_heuristic(self, settings, storage):
        detector = Detector(settings, storage, geo=None)
        assert detector.evaluate(make_offer(destination="BKK", price=20)) is None

    def test_thin_history_falls_back_to_heuristic(self, settings, storage, geo):
        """Three observations is not a baseline, even though it is history."""
        seed_history(storage, [500, 510, 495], destination="BKK")
        detector = Detector(settings, storage, geo)
        deal = detector.evaluate(make_offer(destination="BKK", price=90))

        assert deal is not None
        assert deal.basis == "heuristic"

    def test_history_from_a_single_day_is_not_trusted(self, settings, storage, geo):
        """Twenty prices scraped in one sweep describe one moment, not a norm."""
        seed_history(storage, [500] * 20, destination="BKK", spread_days=1)
        detector = Detector(settings, storage, geo)
        deal = detector.evaluate(make_offer(destination="BKK", price=90))

        assert deal is not None
        assert deal.basis == "heuristic"


class TestAlertGating:
    def _fire(self, detector):
        return detector.evaluate(make_offer(price=95))

    def test_same_deal_is_not_sent_twice(self, settings, storage, geo):
        seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
        detector = Detector(settings, storage, geo)

        deal = self._fire(detector)
        assert detector.should_alert(deal) is True
        storage.record_alert(deal)
        assert detector.should_alert(deal) is False

    def test_marginally_better_price_stays_quiet(self, settings, storage, geo):
        seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
        detector = Detector(settings, storage, geo)

        first = self._fire(detector)
        storage.record_alert(first)

        barely_better = detector.evaluate(make_offer(price=92))
        assert barely_better is not None
        assert detector.should_alert(barely_better) is False

    def test_substantially_better_price_breaks_through(self, settings, storage, geo):
        seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
        detector = Detector(settings, storage, geo)

        first = self._fire(detector)
        storage.record_alert(first)

        much_better = detector.evaluate(make_offer(price=60))
        assert much_better is not None
        assert detector.should_alert(much_better) is True


class TestGuards:
    def test_zero_and_negative_prices_are_ignored(self, settings, storage, geo):
        detector = Detector(settings, storage, geo)
        for price in (0.0, -10.0):
            offer = Offer(
                origin="TLV",
                destination="BKK",
                price=price,
                currency="usd",
                depart_date=date(2026, 9, 1),
            )
            assert detector.evaluate(offer) is None
