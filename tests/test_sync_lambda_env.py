from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "deploy" / "sync_lambda_env.py"


def load(monkeypatch, **env):
    """Import the deploy script fresh with a controlled environment.

    It reads os.environ at import time, so each case needs its own module
    instance rather than a shared one.
    """
    for key in list(env):
        monkeypatch.setenv(key, env[key])
    spec = importlib.util.spec_from_file_location("sync_lambda_env", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = {
    "STATE_BUCKET": "state-bucket",
    "SITE_BUCKET": "site-bucket",
    "TRAVELPAYOUTS_TOKEN": "tp-token",
}


def test_full_variable_set_is_always_sent(monkeypatch):
    """A partial map would wipe the bucket names, since AWS replaces rather
    than merges."""
    env = load(monkeypatch, **BASE).build()

    assert env["DATA_DIR"] == "/tmp/flight-radar"
    assert env["STATE_BUCKET"] == "state-bucket"
    assert env["SITE_BUCKET"] == "site-bucket"
    assert env["STATE_PREFIX"] == "state"
    assert env["SITE_DATA_KEY"] == "data/deals.json"
    assert env["TRAVELPAYOUTS_TOKEN"] == "tp-token"


def test_missing_token_aborts_instead_of_blanking_it(monkeypatch):
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "")
    with pytest.raises(SystemExit) as exc:
        load(monkeypatch, STATE_BUCKET="s", SITE_BUCKET="b").build()
    assert "TRAVELPAYOUTS_TOKEN" in str(exc.value)


def test_whitespace_only_token_is_treated_as_missing(monkeypatch):
    with pytest.raises(SystemExit):
        load(monkeypatch, **{**BASE, "TRAVELPAYOUTS_TOKEN": "   "}).build()


def test_missing_bucket_aborts(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        load(monkeypatch, **{**BASE, "STATE_BUCKET": ""}).build()
    assert "STATE_BUCKET" in str(exc.value)


def test_optional_values_are_forwarded_when_set(monkeypatch):
    env = load(monkeypatch, **BASE, TELEGRAM_BOT_TOKEN="bot", MIN_Z_SCORE="3.5").build()
    assert env["TELEGRAM_BOT_TOKEN"] == "bot"
    assert env["MIN_Z_SCORE"] == "3.5"


def test_unset_optional_values_are_omitted_not_blanked(monkeypatch):
    """An empty MIN_Z_SCORE would override the tuned default with garbage."""
    env = load(monkeypatch, **BASE, MIN_Z_SCORE="", TELEGRAM_BOT_TOKEN="").build()
    assert "MIN_Z_SCORE" not in env
    assert "TELEGRAM_BOT_TOKEN" not in env


def test_values_with_commas_and_equals_survive(monkeypatch):
    """The reason this writes JSON rather than using the CLI's Variables=
    shorthand, which splits on exactly these characters."""
    nasty = "abc,def=ghi"
    env = load(monkeypatch, **{**BASE, "TRAVELPAYOUTS_TOKEN": nasty}).build()
    assert env["TRAVELPAYOUTS_TOKEN"] == nasty

    import json

    assert json.loads(json.dumps({"Variables": env}))["Variables"]["TRAVELPAYOUTS_TOKEN"] == nasty
