from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from flight_radar.state import S3State, state_from


class FakeS3:
    """In-memory stand-in that mimics the handful of calls S3State makes."""

    def __init__(self, objects: dict[str, bytes] | None = None, fail_on: str = "") -> None:
        self.objects = dict(objects or {})
        self.fail_on = fail_on
        self.uploaded: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        outer = self

        class P:
            def paginate(self, Bucket, Prefix):
                items = [{"Key": k} for k in outer.objects if k.startswith(Prefix)]
                return [{"Contents": items}] if items else [{}]

        return P()

    def download_file(self, Bucket, Key, path):
        Path(path).write_bytes(self.objects[Key])

    def upload_file(self, path, Bucket, Key):
        if self.fail_on and self.fail_on in Key:
            raise RuntimeError("upload denied")
        self.objects[Key] = Path(path).read_bytes()
        self.uploaded.append(Key)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("404")
        return {}


class TestPull:
    def test_restores_files_preserving_layout(self, tmp_path):
        s3 = FakeS3({
            "state/flight_radar.sqlite3": b"DB",
            "state/cache/airports.json": b"[]",
        })
        n = S3State("b", "state", tmp_path, client=s3).pull()

        assert n == 2
        assert (tmp_path / "flight_radar.sqlite3").read_bytes() == b"DB"
        assert (tmp_path / "cache" / "airports.json").read_bytes() == b"[]"

    def test_empty_prefix_is_a_normal_first_run(self, tmp_path):
        assert S3State("b", "state", tmp_path, client=FakeS3()).pull() == 0
        assert tmp_path.exists()

    def test_s3_failure_degrades_to_empty_rather_than_raising(self, tmp_path):
        class Broken(FakeS3):
            def get_paginator(self, name):
                raise RuntimeError("network down")

        assert S3State("b", "state", tmp_path, client=Broken()).pull() == 0


class TestPush:
    def test_uploads_the_database(self, tmp_path):
        (tmp_path / "flight_radar.sqlite3").write_bytes(b"DB")
        s3 = FakeS3()
        assert S3State("b", "state", tmp_path, client=s3).push() == 1
        assert s3.objects["state/flight_radar.sqlite3"] == b"DB"

    def test_database_is_rewritten_even_when_present(self, tmp_path):
        (tmp_path / "flight_radar.sqlite3").write_bytes(b"NEW")
        s3 = FakeS3({"state/flight_radar.sqlite3": b"OLD"})
        S3State("b", "state", tmp_path, client=s3).push()
        assert s3.objects["state/flight_radar.sqlite3"] == b"NEW"

    def test_reference_tables_are_not_re_uploaded_every_run(self, tmp_path):
        """They are megabytes and change twice a year; re-sending is waste."""
        (tmp_path / "cache").mkdir()
        (tmp_path / "cache" / "airports.json").write_bytes(b"[]")
        (tmp_path / "flight_radar.sqlite3").write_bytes(b"DB")
        s3 = FakeS3({"state/cache/airports.json": b"[]"})

        S3State("b", "state", tmp_path, client=s3).push()
        assert s3.uploaded == ["state/flight_radar.sqlite3"]

    def test_new_cache_file_is_uploaded_once(self, tmp_path):
        (tmp_path / "cache").mkdir()
        (tmp_path / "cache" / "cities.json").write_bytes(b"[]")
        s3 = FakeS3()
        S3State("b", "state", tmp_path, client=s3).push()
        assert "state/cache/cities.json" in s3.objects

    def test_a_failed_database_upload_is_fatal(self, tmp_path):
        """Silently losing the history would blind the detector for weeks."""
        (tmp_path / "flight_radar.sqlite3").write_bytes(b"DB")
        with pytest.raises(RuntimeError):
            S3State("b", "state", tmp_path, client=FakeS3(fail_on="sqlite3")).push()

    def test_a_failed_cache_upload_is_tolerated(self, tmp_path):
        (tmp_path / "cache").mkdir()
        (tmp_path / "cache" / "airports.json").write_bytes(b"[]")
        (tmp_path / "flight_radar.sqlite3").write_bytes(b"DB")
        s3 = FakeS3(fail_on="airports")
        assert S3State("b", "state", tmp_path, client=s3).push() == 1


class TestRoundTrip:
    def test_history_survives_a_stateless_invocation(self, tmp_path):
        """The property the whole Lambda design depends on."""
        from flight_radar.storage import Storage

        from .conftest import seed_history

        s3 = FakeS3()
        run_one = tmp_path / "run1"
        run_one.mkdir()
        store = Storage(run_one / "flight_radar.sqlite3")
        seed_history(store, [200, 210, 190])
        store.close()
        S3State("b", "state", run_one, client=s3).push()

        # A completely fresh container.
        run_two = tmp_path / "run2"
        S3State("b", "state", run_two, client=s3).pull()
        restored = Storage(run_two / "flight_radar.sqlite3")

        assert restored.stats()["observations"] == 3
        restored.close()


class TestFactory:
    def test_disabled_without_a_bucket(self, settings):
        assert state_from(settings) is None

    def test_enabled_with_a_bucket(self, settings):
        st = state_from(replace(settings, state_bucket="b"), client=FakeS3())
        assert isinstance(st, S3State)
        assert st.prefix == "state"
