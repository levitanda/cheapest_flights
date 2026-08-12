from __future__ import annotations

import json

import pytest

from flight_radar.geo import Geo, expected_round_trip_usd, haversine_km


class TestHaversine:
    def test_known_distance_tlv_athens(self):
        # ~1160 km in reality.
        km = haversine_km(32.0114, 34.8867, 37.9364, 23.9445)
        assert km == pytest.approx(1160, rel=0.05)

    def test_zero_for_identical_points(self):
        assert haversine_km(32.0, 34.0, 32.0, 34.0) == pytest.approx(0.0)


class TestExpectedPrice:
    def test_grows_with_distance(self):
        short = expected_round_trip_usd(500)
        medium = expected_round_trip_usd(3000)
        long_haul = expected_round_trip_usd(9000)
        assert short < medium < long_haul

    def test_per_km_cost_falls_with_distance(self):
        """The curve has to bend, otherwise long-haul expectations become
        absurd and every intercontinental fare looks like an error fare."""
        near_rate = expected_round_trip_usd(1000) / 1000
        far_rate = expected_round_trip_usd(9000) / 9000
        assert far_rate < near_rate

    def test_stays_in_a_sane_range_for_real_routes(self):
        assert 100 < expected_round_trip_usd(1160) < 250     # TLV-ATH
        assert 400 < expected_round_trip_usd(7300) < 800     # TLV-BKK

    def test_zero_distance_is_the_base_fare(self):
        assert expected_round_trip_usd(0) == pytest.approx(40.0)


class TestGeo:
    def test_lookups(self, geo):
        assert geo.coords("TLV") is not None
        assert geo.country("BKK") == "TH"
        assert geo.name("ATH", "ru") == "Афины"

    def test_name_falls_back_to_english_then_code(self, geo):
        assert geo.name("BKK", "fr") == "Suvarnabhumi"
        assert geo.name("ZZZ") == "ZZZ"

    def test_unknown_airport_has_no_distance(self, geo):
        assert geo.distance_km("TLV", "ZZZ") is None
        assert geo.expected_price("TLV", "ZZZ", one_way=False) is None

    def test_one_way_is_cheaper_but_not_half(self, geo):
        round_trip = geo.expected_price("TLV", "BKK", one_way=False)
        one_way = geo.expected_price("TLV", "BKK", one_way=True)
        assert round_trip / 2 < one_way < round_trip

    def test_results_are_cached_on_disk(self, tmp_path):
        calls = []

        def counting_fetch(url):
            calls.append(url)
            return [
                {
                    "code": "TLV",
                    "name": "Ben Gurion",
                    "coordinates": {"lat": 32.0, "lon": 34.9},
                    "country_code": "IL",
                }
            ]

        Geo(tmp_path / "cache", fetch=counting_fetch).load()
        first_round = len(calls)

        Geo(tmp_path / "cache", fetch=counting_fetch).load()
        assert len(calls) == first_round  # served from disk

    def test_a_failing_source_does_not_crash_the_loader(self, tmp_path):
        def broken_fetch(url):
            raise RuntimeError("network down")

        geo = Geo(tmp_path / "cache", fetch=broken_fetch)
        geo.load()
        assert geo.coords("TLV") is None

    def test_cache_filenames_carry_the_language(self, tmp_path):
        """Otherwise switching language keeps serving the stale dump forever,
        because the cache is keyed by filename alone."""
        payload = [{"code": "TLV", "name": "Тель-Авив",
                    "coordinates": {"lat": 32.0, "lon": 34.9}, "country_code": "IL"}]
        cache = tmp_path / "cache"
        Geo(cache, fetch=lambda url: payload, lang="ru").load()

        assert (cache / "cities.ru.json").exists()
        assert (cache / "airports.ru.json").exists()

    def test_corrupt_cache_is_refetched(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "airports.ru.json").write_text("{not json", encoding="utf-8")

        payload = [
            {
                "code": "TLV",
                "name": "Ben Gurion",
                "coordinates": {"lat": 32.0, "lon": 34.9},
                "country_code": "IL",
            }
        ]
        geo = Geo(cache_dir, fetch=lambda url: payload if "airports" in url else [])
        geo.load()
        assert geo.coords("TLV") == (32.0, 34.9)
        assert json.loads((cache_dir / "airports.ru.json").read_text())

    def test_city_name_wins_over_the_airport_name(self, tmp_path):
        """'Афины' belongs on the page, not 'Eleftherios Venizelos
        International Airport' — but the airport's coordinates are the precise
        ones and must still be used for distance."""
        cities = [{"code": "ATH", "name": "Athens",
                   "coordinates": {"lat": 37.98, "lon": 23.73},
                   "country_code": "GR", "name_translations": {"ru": "Афины"}}]
        airports = [{"code": "ATH", "name": "Eleftherios Venizelos International Airport",
                     "coordinates": {"lat": 37.9364, "lon": 23.9445},
                     "country_code": "GR"}]

        geo = Geo(tmp_path / "c",
                  fetch=lambda url: airports if "airports" in url else cities)
        geo.load()

        assert geo.name("ATH") == "Афины"
        assert geo.coords("ATH") == (37.9364, 23.9445)

    def test_airport_only_codes_still_resolve(self, tmp_path):
        airports = [{"code": "XXX", "name": "Somewhere Field",
                     "coordinates": {"lat": 1.0, "lon": 2.0}, "country_code": "ZZ"}]
        geo = Geo(tmp_path / "c",
                  fetch=lambda url: airports if "airports" in url else [])
        geo.load()

        assert geo.name("XXX") == "Somewhere Field"
        assert geo.country("XXX") == "ZZ"

    def test_entries_without_coordinates_are_skipped(self, tmp_path):
        payload = [
            {"code": "AAA", "name": "No coords"},
            {"code": "BBB", "name": "Fine", "coordinates": {"lat": 1.0, "lon": 2.0}},
        ]
        geo = Geo(tmp_path / "c", fetch=lambda url: payload if "airports" in url else [])
        geo.load()
        assert geo.coords("AAA") is None
        assert geo.coords("BBB") == (1.0, 2.0)
