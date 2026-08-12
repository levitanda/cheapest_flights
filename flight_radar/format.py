"""Rendering deals into something worth reading on a phone.

The alert has to answer three questions before the user decides to tap:
what and when, how good it is relative to normal, and where to verify it.
Everything else is noise.
"""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Optional

from .geo import Geo
from .models import (
    TIER_ERROR_FARE,
    TIER_EXCEPTIONAL,
    TIER_GOOD,
    TIER_GREAT,
    Deal,
)
from .providers.base import google_flights_url

_TIER_LABEL = {
    TIER_GOOD: ("🟢", "Хорошая цена"),
    TIER_GREAT: ("🔵", "Отличная цена"),
    TIER_EXCEPTIONAL: ("🟣", "Исключительная цена"),
    TIER_ERROR_FARE: ("🔴", "Похоже на ошибочный тариф"),
}

_CURRENCY_SYMBOL = {"usd": "$", "eur": "€", "ils": "₪", "gbp": "£", "rub": "₽"}

_MONTHS_RU = (
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


def money(amount: float, currency: str) -> str:
    symbol = _CURRENCY_SYMBOL.get(currency.lower())
    rounded = f"{amount:,.0f}".replace(",", " ")
    return f"{symbol}{rounded}" if symbol else f"{rounded} {currency.upper()}"


def short_date(value: Optional[date]) -> str:
    return f"{value.day} {_MONTHS_RU[value.month - 1]}" if value else "?"


def date_range(depart: Optional[date], ret: Optional[date]) -> str:
    if depart and ret:
        return f"{short_date(depart)} — {short_date(ret)}"
    if depart:
        return f"{short_date(depart)}, в одну сторону"
    return "даты уточняются"


def _place(code: str, geo: Optional[Geo]) -> str:
    """'Афины (ATH)', or bare 'ATH' when no name is known.

    The reference tables can be unavailable — offline, or a first run behind a
    firewall — and letting that render as 'ATH (ATH)' looks like a bug.
    """
    name = geo.name(code) if geo else code
    return code if name == code else f"{name} ({code})"


def route_line(deal: Deal, geo: Optional[Geo]) -> str:
    return f"{_place(deal.offer.origin, geo)} → {_place(deal.offer.destination, geo)}"


def render_telegram(deal: Deal, booking_url: str, geo: Optional[Geo] = None) -> str:
    """HTML for Telegram's `parse_mode=HTML`."""
    icon, label = _TIER_LABEL.get(deal.tier, _TIER_LABEL[TIER_GOOD])
    offer = deal.offer
    currency = offer.currency

    lines = [
        f"{icon} <b>{escape(label)}</b>",
        f"<b>{escape(route_line(deal, geo))}</b>",
        "",
        f"💸 <b>{escape(money(offer.price, currency))}</b>"
        f"  <s>{escape(money(deal.baseline_price, currency))}</s>"
        f"  −{deal.drop_pct:.0%}",
        f"📅 {escape(date_range(offer.depart_date, offer.return_date))}",
    ]

    details = []
    if offer.trip_nights is not None:
        details.append(f"{offer.trip_nights} ноч.")
    if offer.transfers == 0:
        details.append("без пересадок")
    elif offer.transfers:
        details.append(f"пересадок: {offer.transfers}")
    if offer.airline:
        details.append(escape(offer.airline))
    if details:
        lines.append("✈️ " + " · ".join(details))

    lines += [
        "",
        f"<i>{escape(deal.reason)}</i>",
        "",
        f'🔗 <a href="{escape(booking_url, quote=True)}">Открыть на Aviasales</a>',
        f'🔎 <a href="{escape(google_flights_url(offer.origin, offer.destination, offer.depart_date, offer.return_date), quote=True)}">'
        "Проверить в Google Flights</a>",
    ]

    if deal.tier == TIER_ERROR_FARE:
        lines += [
            "",
            "⚠️ Ошибочные тарифы живут часы. Бронировать сразу, "
            "отели и планы — только после подтверждения от авиакомпании.",
        ]
    elif deal.basis == "heuristic":
        lines += ["", "ℹ️ Оценка без истории цен — проверьте по ссылкам ниже."]

    return "\n".join(lines)


def render_plain(deal: Deal, booking_url: str, geo: Optional[Geo] = None) -> str:
    """Plain text for Pushover and the console."""
    _, label = _TIER_LABEL.get(deal.tier, _TIER_LABEL[TIER_GOOD])
    offer = deal.offer
    return "\n".join(
        [
            f"{label}: {route_line(deal, geo)}",
            f"{money(offer.price, offer.currency)} вместо "
            f"{money(deal.baseline_price, offer.currency)} (−{deal.drop_pct:.0%})",
            date_range(offer.depart_date, offer.return_date),
            deal.reason,
            booking_url,
        ]
    )


def render_title(deal: Deal, geo: Optional[Geo] = None) -> str:
    icon, _ = _TIER_LABEL.get(deal.tier, _TIER_LABEL[TIER_GOOD])
    destination = geo.name(deal.offer.destination) if geo else deal.offer.destination
    return f"{icon} {destination} — {money(deal.offer.price, deal.offer.currency)}"
