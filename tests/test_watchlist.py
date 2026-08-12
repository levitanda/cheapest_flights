from __future__ import annotations

from datetime import date

from flight_radar import watchlist as wl

from .conftest import make_offer


class TestLoading:
    def test_missing_file_yields_the_default_sweep(self, tmp_path):
        entries = wl.load(tmp_path / "nope.toml")
        assert len(entries) == 1
        assert entries[0].origin == "TLV"
        assert entries[0].mode == wl.MODE_DISCOVER

    def test_parses_entries_and_defaults(self, tmp_path):
        path = tmp_path / "watchlist.toml"
        path.write_text(
            """
[defaults]
max_nights = 14

[[watch]]
origin = "tlv"
mode = "discover"
exclude = ["vda"]

[[watch]]
origin = "TLV"
destination = "bkk"
months_ahead = 3
min_nights = 7
""",
            encoding="utf-8",
        )
        entries = wl.load(path)

        assert len(entries) == 2
        assert entries[0].origin == "TLV"
        assert entries[0].exclude == frozenset({"VDA"})
        assert entries[0].max_nights == 14  # inherited from [defaults]

        # A destination without an explicit mode implies tracking.
        assert entries[1].mode == wl.MODE_TRACK
        assert entries[1].destination == "BKK"
        assert entries[1].min_nights == 7

    def test_entry_without_origin_is_skipped(self, tmp_path):
        path = tmp_path / "w.toml"
        path.write_text('[[watch]]\ndestination = "BKK"\n', encoding="utf-8")
        assert wl.load(path) == wl.DEFAULT_WATCHLIST

    def test_track_without_destination_is_skipped(self, tmp_path):
        path = tmp_path / "w.toml"
        path.write_text('[[watch]]\norigin = "TLV"\nmode = "track"\n', encoding="utf-8")
        assert wl.load(path) == wl.DEFAULT_WATCHLIST

    def test_unknown_mode_degrades_to_discover(self, tmp_path):
        path = tmp_path / "w.toml"
        path.write_text('[[watch]]\norigin = "TLV"\nmode = "telepathy"\n', encoding="utf-8")
        assert wl.load(path)[0].mode == wl.MODE_DISCOVER


class TestFilters:
    def test_excluded_destination_is_rejected(self):
        entry = wl.WatchEntry(origin="TLV", exclude=frozenset({"ATH"}))
        assert entry.accepts(make_offer(destination="ATH")) is False

    def test_country_allowlist(self):
        entry = wl.WatchEntry(origin="TLV", include_countries=frozenset({"GR"}))
        assert entry.accepts(make_offer(destination="ATH"), country="GR") is True
        assert entry.accepts(make_offer(destination="BKK"), country="TH") is False

    def test_price_ceiling(self):
        entry = wl.WatchEntry(origin="TLV", max_price=300)
        assert entry.accepts(make_offer(price=250)) is True
        assert entry.accepts(make_offer(price=400)) is False

    def test_trip_length_window(self):
        entry = wl.WatchEntry(origin="TLV", min_nights=5, max_nights=10)
        assert entry.accepts(make_offer(depart=date(2026, 9, 1), ret=date(2026, 9, 8)))
        assert not entry.accepts(make_offer(depart=date(2026, 9, 1), ret=date(2026, 9, 3)))
        assert not entry.accepts(make_offer(depart=date(2026, 9, 1), ret=date(2026, 9, 30)))

    def test_length_filters_do_not_reject_one_ways(self):
        """A one-way has no length, which is not the same as a wrong length."""
        entry = wl.WatchEntry(origin="TLV", min_nights=5, max_nights=10)
        assert entry.accepts(make_offer(ret=None)) is True

    def test_direct_only(self):
        entry = wl.WatchEntry(origin="TLV", direct_only=True)
        assert entry.accepts(make_offer(transfers=0)) is True
        assert entry.accepts(make_offer(transfers=2)) is False
        # Unknown connection count is kept rather than silently discarded.
        assert entry.accepts(make_offer(transfers=None)) is True


class TestMonths:
    def test_rolls_over_the_year_boundary(self):
        entry = wl.WatchEntry(origin="TLV", destination="BKK", months_ahead=4)
        assert entry.months(today=date(2026, 11, 15)) == [
            "2026-11",
            "2026-12",
            "2027-01",
            "2027-02",
        ]

    def test_always_returns_at_least_one_month(self):
        entry = wl.WatchEntry(origin="TLV", destination="BKK", months_ahead=0)
        assert len(entry.months(today=date(2026, 5, 1))) == 1
