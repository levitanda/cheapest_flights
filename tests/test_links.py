"""Comparison links.

These are searches on other sites, never the fare we found. Only the
provider's own booking link carries the quoted price, and the UI has to say
so — presenting a search as "buy it here for $62" is the complaint that made
the off-the-shelf deal clubs untrustworthy.
"""

from __future__ import annotations

from datetime import date

import pytest

from flight_radar.providers.base import (
    comparison_links,
    google_flights_url,
    kiwi_url,
    skyscanner_il_url,
)

DEPART = date(2026, 10, 5)
RETURN = date(2026, 10, 12)


class TestSkyscanner:
    def test_israeli_domain_and_locale(self):
        url = skyscanner_il_url("TLV", "ATH", DEPART, RETURN)
        assert url.startswith("https://www.skyscanner.co.il/")
        assert "locale=he-IL" in url
        assert "market=IL" in url

    def test_dates_are_yymmdd_path_segments(self):
        assert "/tlv/ath/261005/261012/" in skyscanner_il_url("TLV", "ATH", DEPART, RETURN)

    def test_one_way_omits_the_return_segment(self):
        url = skyscanner_il_url("TLV", "ATH", DEPART, None)
        assert "/tlv/ath/261005/?" in url

    def test_missing_dates_degrade_to_a_route_search(self):
        assert skyscanner_il_url("TLV", "ATH", None, None).startswith(
            "https://www.skyscanner.co.il/transport/flights/tlv/ath/?"
        )


class TestGoogleFlights:
    def test_targets_the_israeli_locale(self):
        url = google_flights_url("TLV", "ATH", DEPART, RETURN)
        assert "gl=IL" in url and "hl=iw" in url

    def test_encodes_the_route_and_dates(self):
        url = google_flights_url("TLV", "ATH", DEPART, RETURN)
        assert "TLV" in url and "ATH" in url and "2026-10-05" in url


class TestKiwi:
    def test_round_trip(self):
        assert kiwi_url("TLV", "ATH", DEPART, RETURN).endswith(
            "/TLV/ATH/2026-10-05/2026-10-12"
        )

    def test_one_way(self):
        assert kiwi_url("TLV", "ATH", DEPART, None).endswith("/TLV/ATH/2026-10-05")


class TestComparisonSet:
    def test_three_independent_sites(self):
        links = comparison_links("TLV", "ATH", DEPART, RETURN)
        assert [l["id"] for l in links] == ["skyscanner", "google", "kiwi"]

    @pytest.mark.parametrize("depart,ret", [(DEPART, RETURN), (DEPART, None), (None, None)])
    def test_every_link_is_absolute_https(self, depart, ret):
        for link in comparison_links("TLV", "ATH", depart, ret):
            assert link["url"].startswith("https://"), link
