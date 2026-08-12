from __future__ import annotations

from dataclasses import replace

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
    provider = FakeProvider([make_offer(price=200), make_offer(destination="ATH", price=210)])
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
            make_offer(destination="BKK", price=250),  # ~50% off
            make_offer(destination="BKK", price=60),   # ~88% off
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
