"""Searchability of destinations we have no price for.

A reader typing "אמסטרדם" got a blank page whenever the scanner had not
happened to see that route — which reads as a broken search rather than as
missing data. The places index exists so the page can always answer.
"""

from __future__ import annotations

from flight_radar.publish import build_payload
from flight_radar.watchlist import MODES, MODE_LATEST

from .conftest import make_offer


def test_index_covers_destinations_with_no_collected_price(storage, geo):
    places = build_payload(storage, geo)["places"]

    for code in ("AMS", "BCN", "LON", "BER", "MAD", "LIS", "VIE", "IST", "DXB"):
        assert code in places, f"{code} is not searchable"


def test_index_carries_every_site_language(storage, geo):
    entry = build_payload(storage, geo)["places"]["AMS"]
    assert set(entry) == {"he", "ru", "en"}
    assert entry["he"] == "אמסטרדם"


def test_priced_destinations_are_included_even_if_not_curated(storage, geo):
    storage.record_offers([make_offer(destination="ZZZ", price=99)])
    assert "ZZZ" in build_payload(storage, geo)["places"]


def test_index_is_present_without_geo(storage):
    # Degrades to whatever is priced rather than exploding.
    storage.record_offers([make_offer(destination="ATH", price=99)])
    assert "ATH" in build_payload(storage, None)["places"]


class TestLatestMode:
    def test_mode_is_accepted_by_the_watchlist(self, tmp_path):
        from flight_radar import watchlist as wl

        path = tmp_path / "w.toml"
        path.write_text('[[watch]]\norigin = "TLV"\nmode = "latest"\n', encoding="utf-8")
        assert wl.load(path)[0].mode == MODE_LATEST

    def test_latest_is_a_known_mode(self):
        assert MODE_LATEST in MODES

    def test_runner_uses_the_broad_endpoint(self, settings, storage, geo):
        from flight_radar.runner import run_scan
        from flight_radar.watchlist import WatchEntry

        class Provider:
            name = "fake"

            def __init__(self):
                self.latest_calls = []
                self.direction_calls = []

            def latest_prices(self, origin, limit=1000):
                self.latest_calls.append(origin)
                return [make_offer(destination="AMS", price=180)]

            def city_directions(self, origin):
                self.direction_calls.append(origin)
                return []

            def prices_for_dates(self, *a, **k):
                return []

            def booking_url(self, offer):
                return "https://example.test"

        provider = Provider()
        report = run_scan(settings, provider, storage,
                          [WatchEntry("TLV", mode=MODE_LATEST)], [], geo)

        assert provider.latest_calls == ["TLV"]
        assert provider.direction_calls == []
        assert report.offers_seen == 1
