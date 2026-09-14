from __future__ import annotations

from dataclasses import replace
from datetime import date

from flight_radar.runner import run_scan
from flight_radar.watchlist import MODE_TRACK, WatchEntry

from .conftest import make_offer, seed_history


class FakeProvider:
    name = "fake"

    def __init__(self, offers=(), directions_error=None):
        self.offers = list(offers)
        self.directions_error = directions_error
        self.direction_calls = []
        self.date_calls = []

    def city_directions(self, origin):
        self.direction_calls.append(origin)
        if self.directions_error:
            raise self.directions_error
        return list(self.offers)

    def prices_for_dates(self, origin, destination, departure_at=None, **kwargs):
        self.date_calls.append((origin, destination, departure_at))
        return list(self.offers)

    def booking_url(self, offer):
        return f"https://example.test/{offer.origin}-{offer.destination}"


class RecordingNotifier:
    name = "recording"

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.sent = []

    def send(self, deal, booking_url):
        self.sent.append((deal, booking_url))
        return self.succeed


def test_scan_stores_offers_and_stays_quiet_on_normal_prices(settings, storage, geo):
    # Distinct dates, or dedupe would correctly collapse them into one fare.
    provider = FakeProvider([
        make_offer(price=200, depart=date(2026, 9, 10), ret=date(2026, 9, 17)),
        make_offer(price=210, depart=date(2026, 10, 10), ret=date(2026, 10, 17)),
    ])
    notifier = RecordingNotifier()

    report = run_scan(settings, provider, storage, [WatchEntry("TLV")], [notifier], geo)

    assert report.offers_seen == 2
    assert report.offers_stored == 2
    assert report.alerted == 0
    assert notifier.sent == []


def test_offer_is_judged_before_it_joins_its_own_baseline(settings, storage, geo):
    """Recording first would let a lone cheap fare drag the median towards
    itself and disqualify the very deal we are trying to catch."""
    seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
    provider = FakeProvider([make_offer(price=95)])
    notifier = RecordingNotifier()

    report = run_scan(settings, provider, storage, [WatchEntry("TLV")], [notifier], geo)

    assert report.alerted == 1
    assert report.offers_stored == 1
    assert len(notifier.sent) == 1


def test_alerts_are_capped_and_the_best_survive(settings, storage, geo):
    seed_history(storage, [500] * 6 + [510] * 6, destination="BKK")
    capped = replace(settings, max_alerts_per_scan=1)
    provider = FakeProvider(
        [
            make_offer(destination="BKK", price=250,   # ~50% off
                       depart=date(2026, 9, 10), ret=date(2026, 9, 17)),
            make_offer(destination="BKK", price=60,    # ~88% off
                       depart=date(2026, 11, 3), ret=date(2026, 11, 10)),
        ]
    )
    notifier = RecordingNotifier()

    report = run_scan(capped, provider, storage, [WatchEntry("TLV")], [notifier], geo)

    assert report.alerted == 1
    assert report.suppressed == 1
    assert notifier.sent[0][0].offer.price == 60


def test_delivery_failure_is_not_recorded_so_it_can_retry(settings, storage, geo):
    seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
    provider = FakeProvider([make_offer(price=95)])
    failing = RecordingNotifier(succeed=False)

    report = run_scan(settings, provider, storage, [WatchEntry("TLV")], [failing], geo)

    assert report.alerted == 0
    assert report.errors
    assert storage.stats()["alerts"] == 0


def test_dry_run_sends_nothing_and_records_nothing(settings, storage, geo):
    seed_history(storage, [200, 210, 195, 205, 220, 190, 215, 200, 205, 198, 212, 207])
    provider = FakeProvider([make_offer(price=95)])
    notifier = RecordingNotifier()

    report = run_scan(
        settings, provider, storage, [WatchEntry("TLV")], [notifier], geo, dry_run=True
    )

    assert report.alerted == 1
    assert notifier.sent == []
    assert storage.stats()["alerts"] == 0


def test_a_failing_route_does_not_abort_the_scan(settings, storage, geo):
    good = FakeProvider([make_offer(price=200)])
    broken = FakeProvider(directions_error=RuntimeError("upstream down"))

    class SplitProvider:
        name = "split"

        def city_directions(self, origin):
            return broken.city_directions(origin) if origin == "VDA" else good.city_directions(origin)

        def prices_for_dates(self, *a, **k):
            return []

        def booking_url(self, offer):
            return "https://example.test"

    report = run_scan(
        settings,
        SplitProvider(),
        storage,
        [WatchEntry("VDA"), WatchEntry("TLV")],
        [RecordingNotifier()],
        geo,
    )

    assert len(report.errors) == 1
    assert report.offers_seen == 1  # the healthy origin still contributed


def test_track_mode_requests_each_month(settings, storage, geo):
    provider = FakeProvider([make_offer(price=200)])
    entry = WatchEntry("TLV", destination="BKK", mode=MODE_TRACK, months_ahead=3)

    run_scan(settings, provider, storage, [entry], [RecordingNotifier()], geo)

    assert len(provider.date_calls) == 3
    assert provider.direction_calls == []


def test_watchlist_filters_are_applied_before_storage(settings, storage, geo):
    provider = FakeProvider([make_offer(destination="ATH", price=200), make_offer(destination="BKK", price=300)])
    entry = WatchEntry("TLV", exclude=frozenset({"BKK"}))

    report = run_scan(settings, provider, storage, [entry], [RecordingNotifier()], geo)

    assert report.offers_seen == 1
    assert report.offers_stored == 1


class TestDedupe:
    """A deep calendar scan returns hundreds of near-identical itineraries per
    month, and every one would land in the buffer that moves through S3 each
    run. Nothing downstream reads anything but the minimum."""

    def test_cheapest_wins_for_the_same_route_and_dates(self):
        from flight_radar.runner import dedupe

        kept = dedupe([
            make_offer(price=200, depart=date(2026, 9, 10), ret=date(2026, 9, 17)),
            make_offer(price=150, depart=date(2026, 9, 10), ret=date(2026, 9, 17)),
        ])
        assert [o.price for o in kept] == [150]

    def test_different_dates_are_different_fares(self):
        from flight_radar.runner import dedupe

        kept = dedupe([
            make_offer(price=200, depart=date(2026, 9, 10), ret=date(2026, 9, 17)),
            make_offer(price=200, depart=date(2026, 9, 11), ret=date(2026, 9, 18)),
        ])
        assert len(kept) == 2

    def test_one_way_is_not_merged_into_the_return(self):
        from flight_radar.runner import dedupe

        kept = dedupe([
            make_offer(price=200, depart=date(2026, 9, 10), ret=date(2026, 9, 17)),
            make_offer(price=120, depart=date(2026, 9, 10), ret=None),
        ])
        assert len(kept) == 2


class TestDeepScan:
    def test_runs_once_per_window_then_holds_off(self, settings, storage, geo):
        from flight_radar.runner import DEEP_SCAN_KEY, deep_scan, ScanReport

        storage.record_offers([make_offer(destination="ATH", price=120,
                                          depart=date(2026, 10, 5))])

        class Calendar:
            name = "cal"

            def __init__(self):
                self.calls = []

            def prices_for_dates(self, origin, destination, departure_at=None, **kw):
                self.calls.append((destination, departure_at))
                return [make_offer(destination=destination, price=99,
                                   depart=date(2026, 10, 20))]

        provider = Calendar()
        first = deep_scan(provider, storage, settings, ["TLV"], ScanReport())
        assert first, "the first run must actually scan"
        assert len(provider.calls) == settings.deep_scan_months

        # Immediately afterwards it must stay quiet — the calendar is a daily
        # job, not a per-sweep one.
        provider.calls.clear()
        assert deep_scan(provider, storage, settings, ["TLV"], ScanReport()) == []
        assert provider.calls == []
        assert storage.get_meta(DEEP_SCAN_KEY)

    def test_a_failing_route_does_not_abort_the_calendar(self, settings, storage, geo):
        from flight_radar.runner import ScanReport, deep_scan

        storage.record_offers([make_offer(destination="ATH", price=120,
                                          depart=date(2026, 10, 5))])

        class Broken:
            name = "broken"

            def prices_for_dates(self, *a, **kw):
                raise RuntimeError("upstream down")

        assert deep_scan(Broken(), storage, settings, ["TLV"], ScanReport()) == []
