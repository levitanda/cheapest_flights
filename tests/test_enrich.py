"""Resolving a bookable link for fares the discovery sweep found.

`city-directions` returns a price and no `link`, so without this every card
from the sweep could only point at a generic search — 26 of 29 on the live
site did exactly that.
"""

from __future__ import annotations

from datetime import date

from flight_radar.models import Offer
from flight_radar.providers.travelpayouts import TravelpayoutsProvider


def offer(destination="ATH", price=100.0, link=None, depart=date(2026, 10, 5),
          ret=date(2026, 10, 12)) -> Offer:
    return Offer(origin="TLV", destination=destination, price=price, currency="usd",
                 depart_date=depart, return_date=ret, deep_link=link)


class StubProvider(TravelpayoutsProvider):
    """Real enrich logic, scripted prices_for_dates."""

    def __init__(self, responses):
        super().__init__(token="t")
        self.responses = responses
        self.calls = []

    def prices_for_dates(self, origin, destination, departure_at=None, **kw):
        self.calls.append((origin, destination, departure_at))
        return self.responses.get(destination, [])


def test_linkless_offer_gains_a_real_link():
    found = offer(price=98.0, link="/search/exact")
    provider = StubProvider({"ATH": [found]})

    result = provider.enrich([offer(price=100.0)])

    assert result[0].deep_link == "/search/exact"
    assert provider.calls == [("TLV", "ATH", "2026-10")]


def test_offers_that_already_have_a_link_are_left_alone():
    provider = StubProvider({})
    original = offer(link="/search/already")

    assert provider.enrich([original])[0] is original
    assert provider.calls == []


def test_a_pricier_itinerary_is_rejected():
    """Swapping in a costlier fare would make the page quote one price and
    link to another."""
    provider = StubProvider({"ATH": [offer(price=180.0, link="/search/pricier")]})

    result = provider.enrich([offer(price=100.0)])
    assert result[0].deep_link is None


def test_a_slightly_pricier_match_is_tolerated():
    """Rounding between endpoints should not throw away a valid link."""
    provider = StubProvider({"ATH": [offer(price=101.0, link="/search/close")]})
    assert provider.enrich([offer(price=100.0)])[0].deep_link == "/search/close"


def test_same_departure_date_is_preferred_over_a_cheaper_other_day():
    provider = StubProvider({"ATH": [
        offer(price=60.0, link="/search/other-day", depart=date(2026, 10, 20)),
        offer(price=95.0, link="/search/same-day", depart=date(2026, 10, 5)),
    ]})

    assert provider.enrich([offer(price=100.0)])[0].deep_link == "/search/same-day"


def test_candidates_without_links_are_ignored():
    provider = StubProvider({"ATH": [offer(price=50.0, link=None)]})
    assert provider.enrich([offer(price=100.0)])[0].deep_link is None


def test_only_the_cheapest_offers_are_enriched():
    """Each enrichment costs an API call, so it is spent on what reaches the
    page rather than on all ~690 results."""
    provider = StubProvider({})
    offers = [offer(destination=f"D{i:02d}", price=float(100 + i)) for i in range(10)]

    provider.enrich(offers, limit=3)
    assert len(provider.calls) == 3
    assert [c[1] for c in provider.calls] == ["D00", "D01", "D02"]


def test_budget_is_spent_per_destination_not_per_offer():
    """The broad sweep clusters hundreds of fares on a few popular routes.
    Picking the globally cheapest N would resolve Larnaca a dozen times and
    leave Amsterdam pointing at a search."""
    provider = StubProvider({})
    offers = (
        [offer(destination="LCA", price=float(50 + i)) for i in range(12)]
        + [offer(destination="AMS", price=230.0)]
    )

    provider.enrich(offers, limit=5)

    assert sorted(c[1] for c in provider.calls) == ["AMS", "LCA"]


def test_the_cheapest_fare_of_a_route_is_the_one_resolved():
    provider = StubProvider({})
    provider.enrich([offer(destination="LCA", price=180.0),
                     offer(destination="LCA", price=48.0)], limit=5)

    assert len(provider.calls) == 1


def test_a_failing_lookup_does_not_lose_the_offer():
    class Exploding(StubProvider):
        def prices_for_dates(self, *a, **kw):
            raise RuntimeError("upstream down")

    provider = Exploding({})
    result = provider.enrich([offer(price=100.0)])

    assert len(result) == 1
    assert result[0].price == 100.0


def test_offers_without_a_departure_date_are_skipped():
    provider = StubProvider({})
    provider.enrich([offer(depart=None)])
    assert provider.calls == []


def test_order_and_count_are_preserved():
    provider = StubProvider({"ATH": [offer(price=90.0, link="/search/x")]})
    offers = [offer(destination="BKK", price=500.0, link="/keep"), offer(price=100.0)]

    result = provider.enrich(offers)
    assert len(result) == 2
    assert result[0].deep_link == "/keep"
    assert result[1].deep_link == "/search/x"
