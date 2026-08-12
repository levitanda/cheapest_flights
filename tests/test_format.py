from __future__ import annotations

from datetime import date

from flight_radar.format import (
    date_range,
    money,
    render_plain,
    render_telegram,
    render_title,
)
from flight_radar.models import TIER_ERROR_FARE, TIER_GREAT, Deal

from .conftest import make_offer


def deal(tier=TIER_GREAT, basis="history", **offer_kwargs) -> Deal:
    return Deal(
        offer=make_offer(**offer_kwargs),
        baseline_price=420.0,
        drop_pct=0.62,
        z_score=3.8,
        tier=tier,
        basis=basis,
        reason="на 62% ниже обычной цены маршрута",
    )


class TestMoney:
    def test_known_currency_uses_a_symbol(self):
        assert money(1234, "usd") == "$1 234"
        assert money(99, "ils") == "₪99"

    def test_unknown_currency_falls_back_to_the_code(self):
        assert money(500, "sek") == "500 SEK"


class TestDateRange:
    def test_round_trip(self):
        assert date_range(date(2026, 9, 12), date(2026, 9, 19)) == "12 сен — 19 сен"

    def test_one_way(self):
        assert date_range(date(2026, 9, 12), None) == "12 сен, в одну сторону"

    def test_unknown(self):
        assert date_range(None, None) == "даты уточняются"


class TestTelegram:
    def test_contains_the_essentials(self, geo):
        html = render_telegram(deal(), "https://example.test/book", geo)

        assert "Тель-Авив" in html and "Афины" in html
        assert "−62%" in html
        assert "https://example.test/book" in html
        assert "google.com/travel/flights" in html

    def test_error_fare_carries_a_warning(self, geo):
        html = render_telegram(deal(tier=TIER_ERROR_FARE), "https://x.test", geo)
        assert "Ошибочные тарифы живут часы" in html

    def test_heuristic_basis_is_disclosed(self, geo):
        html = render_telegram(deal(basis="heuristic"), "https://x.test", geo)
        assert "без истории цен" in html

    def test_url_is_attribute_escaped(self, geo):
        html = render_telegram(deal(), 'https://x.test/?a=1&b="2"', geo)
        assert "&amp;b=&quot;2&quot;" in html

    def test_airline_text_cannot_inject_markup(self, geo):
        html = render_telegram(deal(airline="<b>evil</b>"), "https://x.test", geo)
        assert "<b>evil</b>" not in html
        assert "&lt;b&gt;evil&lt;/b&gt;" in html

    def test_works_without_geo(self):
        html = render_telegram(deal(), "https://x.test", None)
        assert "TLV" in html and "ATH" in html

    def test_unknown_airport_is_not_rendered_twice(self, geo):
        """'ZZZ (ZZZ)' reads as a rendering bug, so it must collapse."""
        html = render_telegram(deal(destination="ZZZ"), "https://x.test", geo)
        assert "ZZZ (ZZZ)" not in html
        assert "Тель-Авив (TLV) → ZZZ" in html

    def test_direct_flight_is_labelled(self, geo):
        assert "без пересадок" in render_telegram(deal(transfers=0), "https://x.test", geo)

    def test_connections_are_counted(self, geo):
        assert "пересадок: 2" in render_telegram(deal(transfers=2), "https://x.test", geo)


class TestPlain:
    def test_has_no_markup_and_keeps_the_link(self, geo):
        text = render_plain(deal(), "https://example.test/book", geo)
        assert "<" not in text
        assert "https://example.test/book" in text

    def test_title_names_the_destination_and_price(self, geo):
        assert "Афины" in render_title(deal(), geo)
        assert "$200" in render_title(deal(), geo)
