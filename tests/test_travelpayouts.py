from __future__ import annotations

from datetime import date

import pytest
import requests

from flight_radar.models import Offer
from flight_radar.providers.travelpayouts import (
    TravelpayoutsProvider,
    _parse_date,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Records requests and replays a queued list of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}})
        return self.responses.pop(0) if self.responses else FakeResponse({"data": []})


def provider(session=None, **kwargs):
    return TravelpayoutsProvider(
        token="tok", currency="usd", session=session, **kwargs
    )


class TestParseDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-09-12T05:30:00+03:00", date(2026, 9, 12)),
            ("2026-09-12T05:30:00Z", date(2026, 9, 12)),
            ("2026-09-12", date(2026, 9, 12)),
            ("2026-09-12 05:30", date(2026, 9, 12)),
        ],
    )
    def test_accepted_shapes(self, raw, expected):
        assert _parse_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "not-a-date", 12345, "0000"])
    def test_rejected_shapes(self, raw):
        assert _parse_date(raw) is None


class TestCityDirections:
    def test_maps_the_keyed_response(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "BKK": {
                                "origin": "TLV",
                                "destination": "BKK",
                                "price": 412,
                                "transfers": 1,
                                "airline": "TK",
                                "departure_at": "2026-10-03T20:15:00Z",
                                "return_at": "2026-10-17T10:00:00Z",
                            },
                            "ATH": {
                                "origin": "TLV",
                                "destination": "ATH",
                                "price": 89,
                                "transfers": 0,
                                "airline": "A3",
                                "departure_at": "2026-09-12",
                                "return_at": "2026-09-19",
                            },
                        },
                    }
                )
            ]
        )
        offers = provider(session).city_directions("TLV")

        assert len(offers) == 2
        athens = next(o for o in offers if o.destination == "ATH")
        assert athens.price == 89
        assert athens.transfers == 0
        assert athens.trip_nights == 7
        assert athens.trip_kind == "rt"
        assert athens.source == "travelpayouts"

    def test_token_and_currency_are_sent(self):
        session = FakeSession([FakeResponse({"success": True, "data": {}})])
        provider(session).city_directions("tlv")

        params = session.calls[0]["params"]
        assert params["token"] == "tok"
        assert params["origin"] == "TLV"
        assert params["currency"] == "usd"

    def test_malformed_rows_are_skipped_not_fatal(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "AAA": "not a dict",
                            "BBB": {"destination": "BBB"},          # no price
                            "CCC": {"destination": "CCC", "price": 0},  # zero price
                            "DDD": {"destination": "DDD", "price": 120},
                        },
                    }
                )
            ]
        )
        offers = provider(session).city_directions("TLV")
        assert [o.destination for o in offers] == ["DDD"]

    def test_api_level_failure_raises(self):
        session = FakeSession([FakeResponse({"success": False, "error": "bad token"})])
        with pytest.raises(RuntimeError, match="bad token"):
            provider(session).city_directions("TLV")


class TestPricesForDates:
    def test_maps_the_list_response(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "success": True,
                        "data": [
                            {
                                "origin": "TLV",
                                "destination": "ATH",
                                "price": 108,
                                "airline": "A3",
                                "departure_at": "2026-09-12T05:30:00+03:00",
                                "return_at": "2026-09-19T21:00:00+03:00",
                                "transfers": 0,
                                "link": "/search/TLV1209ATH1909",
                            }
                        ],
                    }
                )
            ]
        )
        offers = provider(session).prices_for_dates("TLV", "ATH", departure_at="2026-09")

        assert len(offers) == 1
        assert offers[0].deep_link == "/search/TLV1209ATH1909"
        assert session.calls[0]["params"]["departure_at"] == "2026-09"

    def test_one_way_and_direct_flags_are_stringified(self):
        session = FakeSession([FakeResponse({"success": True, "data": []})])
        provider(session).prices_for_dates("TLV", "ATH", one_way=True, direct=True)

        params = session.calls[0]["params"]
        assert params["one_way"] == "true"
        assert params["direct"] == "true"


class TestRetries:
    def test_transient_500_is_retried(self, monkeypatch):
        monkeypatch.setattr("flight_radar.providers.travelpayouts.time.sleep", lambda s: None)
        session = FakeSession(
            [
                FakeResponse({}, status_code=503),
                FakeResponse({"success": True, "data": {"ATH": {"price": 90}}}),
            ]
        )
        offers = provider(session).city_directions("TLV")

        assert len(session.calls) == 2
        assert len(offers) == 1

    def test_gives_up_after_the_last_retry(self, monkeypatch):
        monkeypatch.setattr("flight_radar.providers.travelpayouts.time.sleep", lambda s: None)
        session = FakeSession([FakeResponse({}, status_code=500) for _ in range(6)])

        with pytest.raises(RuntimeError, match="failed after retries"):
            provider(session).city_directions("TLV")

    def test_client_errors_are_not_retried(self, monkeypatch):
        monkeypatch.setattr("flight_radar.providers.travelpayouts.time.sleep", lambda s: None)
        session = FakeSession([FakeResponse({}, status_code=401)])

        with pytest.raises(RuntimeError):
            provider(session).city_directions("TLV")
        assert len(session.calls) == 1


class TestBookingUrl:
    def test_relative_link_is_absolutised(self):
        offer = Offer(
            origin="TLV",
            destination="ATH",
            price=100,
            currency="usd",
            deep_link="/search/TLV1209ATH1909",
        )
        url = provider().booking_url(offer)
        assert url == "https://www.aviasales.com/search/TLV1209ATH1909"

    def test_marker_is_appended(self):
        offer = Offer(
            origin="TLV",
            destination="ATH",
            price=100,
            currency="usd",
            deep_link="/search/X",
        )
        url = provider(marker="777").booking_url(offer)
        assert url.endswith("?marker=777")

    def test_marker_respects_an_existing_query_string(self):
        offer = Offer(
            origin="TLV",
            destination="ATH",
            price=100,
            currency="usd",
            deep_link="/search/X?t=1",
        )
        assert provider(marker="777").booking_url(offer).endswith("&marker=777")

    def test_search_url_is_rebuilt_when_the_link_is_missing(self):
        offer = Offer(
            origin="TLV",
            destination="ATH",
            price=100,
            currency="usd",
            depart_date=date(2026, 9, 12),
            return_date=date(2026, 9, 19),
        )
        assert provider().booking_url(offer) == (
            "https://www.aviasales.com/search/TLV1209ATH19091"
        )

    def test_one_way_search_url_omits_the_return_leg(self):
        offer = Offer(
            origin="TLV",
            destination="ATH",
            price=100,
            currency="usd",
            depart_date=date(2026, 9, 12),
        )
        assert provider().booking_url(offer).endswith("/TLV1209ATH1")


def test_token_is_required():
    with pytest.raises(ValueError):
        TravelpayoutsProvider(token="")
