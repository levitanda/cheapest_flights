"""The 'cheapest right now' block — what the site shows before any history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flight_radar.publish import build_payload

from .conftest import make_offer


def test_cheapest_per_route_is_exported(storage, geo):
    storage.record_offers([
        make_offer(destination="ATH", price=200),
        make_offer(destination="ATH", price=111),
        make_offer(destination="LCA", price=62),
    ])
    current = build_payload(storage, geo)["current"]

    assert [c["destination"] for c in current] == ["LCA", "ATH"]  # cheapest first
    assert current[1]["price"] == 111


def test_names_and_country_are_resolved(storage, geo):
    storage.record_offers([make_offer(destination="ATH", price=111)])
    row = build_payload(storage, geo)["current"][0]

    assert row["destination_name"] == "Афины"
    assert row["country"] == "GR"


def test_a_booking_url_is_always_present(storage, geo):
    """Rows read back from the database have no provider attached, so the URL
    has to be reconstructible from the route and dates alone."""
    storage.record_offers([make_offer(destination="ATH", price=111)])
    url = build_payload(storage, geo)["current"][0]["url"]

    assert url.startswith("https://www.aviasales.com/search/TLV")
    assert "ATH" in url


def test_stored_deep_link_wins_over_the_reconstructed_one(storage, geo):
    storage.record_offers([make_offer(destination="ATH", price=111,
                                      deep_link="/search/exact-itinerary")])
    assert build_payload(storage, geo)["current"][0]["url"] == (
        "https://www.aviasales.com/search/exact-itinerary"
    )


def test_affiliate_marker_is_applied(storage, geo):
    storage.record_offers([make_offer(destination="ATH", price=111)])
    url = build_payload(storage, geo, marker="777")["current"][0]["url"]
    assert url.endswith("marker=777")


def test_stale_observations_are_excluded(storage, geo):
    """A three-week-old fare is not 'the price right now'."""
    old = datetime.now(timezone.utc) - timedelta(days=21)
    storage.record_offers([
        make_offer(destination="BKK", price=9, observed_at=old),
        make_offer(destination="ATH", price=111),
    ])
    assert [c["destination"] for c in build_payload(storage, geo)["current"]] == ["ATH"]


def test_round_trip_and_one_way_are_listed_separately(storage, geo):
    storage.record_offers([
        make_offer(destination="ATH", price=111),
        make_offer(destination="ATH", price=70, ret=None),
    ])
    current = build_payload(storage, geo)["current"]
    assert len(current) == 2
    assert {c["return_date"] is None for c in current} == {True, False}


def test_empty_database_yields_an_empty_list(storage, geo):
    assert build_payload(storage, geo)["current"] == []
