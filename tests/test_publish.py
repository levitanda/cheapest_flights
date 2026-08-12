from __future__ import annotations

import json

from flight_radar.models import Deal
from flight_radar.publish import S3Publisher, build_payload, publisher_from

from .conftest import make_offer, seed_history


def deal(price=95.0, tier="great", **offer_kwargs) -> Deal:
    return Deal(
        offer=make_offer(price=price, **offer_kwargs),
        baseline_price=210.0,
        drop_pct=0.55,
        z_score=3.4,
        tier=tier,
        basis="history",
        reason="тест",
    )


class TestPayload:
    def test_empty_database_still_produces_a_valid_document(self, storage, geo):
        payload = build_payload(storage, geo)

        assert payload["schema"] == 3
        assert payload["deals"] == []
        assert payload["current"] == []
        assert payload["routes"] == []
        assert payload["stats"]["alerts"] == 0
        assert payload["generated_at"].endswith("+00:00")

    def test_deal_is_exported_with_resolved_names(self, storage, geo):
        storage.record_alert(deal(), url="https://example.test/book")
        payload = build_payload(storage, geo)

        row = payload["deals"][0]
        assert row["destination"] == "ATH"
        assert row["names"]["ru"] == "Афины"
        assert row["names"]["he"] == "אתונה"
        assert row["country"] == "GR"
        assert row["url"] == "https://example.test/book"
        assert row["depart_date"] == "2026-09-10"

    def test_alert_without_a_url_exports_null_not_empty_string(self, storage, geo):
        storage.record_alert(deal())
        assert build_payload(storage, geo)["deals"][0]["url"] is None

    def test_routes_come_from_observations(self, storage, geo):
        seed_history(storage, [200, 180, 220])
        payload = build_payload(storage, geo)

        route = payload["routes"][0]
        assert route["destination"] == "ATH"
        assert route["observations"] == 3
        assert route["cheapest"] == 180

    def test_deal_limit_is_honoured(self, storage, geo):
        for price in range(100, 130):
            storage.record_alert(deal(price=float(price)))
        assert len(build_payload(storage, geo, deal_limit=5)["deals"]) == 5

    def test_payload_is_json_serialisable_without_ascii_escapes(self, storage, geo):
        storage.record_alert(deal())
        text = json.dumps(build_payload(storage, geo), ensure_ascii=False)
        assert "Афины" in text

    def test_works_without_geo(self, storage):
        storage.record_alert(deal())
        row = build_payload(storage, None)["deals"][0]
        assert row["names"] == {"he": "ATH", "ru": "ATH", "en": "ATH"}
        assert row["country"] == ""


class TestPublisher:
    def test_not_configured_when_no_bucket(self, settings):
        assert publisher_from(settings) is None

    def test_configured_when_bucket_present(self, settings):
        from dataclasses import replace

        pub = publisher_from(replace(settings, site_bucket="my-bucket"))
        assert isinstance(pub, S3Publisher)
        assert pub.bucket == "my-bucket"

    def test_upload_failure_is_reported_not_raised(self, monkeypatch, storage, geo):
        """A dead S3 must not take down a scan that already collected prices."""
        import flight_radar.publish as mod

        class Boom:
            def client(self, name):
                raise RuntimeError("no credentials")

        monkeypatch.setitem(__import__("sys").modules, "boto3", Boom())
        assert S3Publisher("b", "k").publish(build_payload(storage, geo)) is False

    def test_successful_upload_sends_json_with_a_short_cache_ttl(
        self, monkeypatch, storage, geo
    ):
        captured = {}

        class FakeS3:
            def put_object(self, **kw):
                captured.update(kw)

        class FakeBoto:
            def client(self, name):
                assert name == "s3"
                return FakeS3()

        monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto())
        storage.record_alert(deal(), url="https://example.test")

        assert S3Publisher("bucket", "data/deals.json").publish(build_payload(storage, geo))
        assert captured["Bucket"] == "bucket"
        assert captured["Key"] == "data/deals.json"
        assert "max-age=120" in captured["CacheControl"]
        assert json.loads(captured["Body"])["deals"][0]["price"] == 95.0
