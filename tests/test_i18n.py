"""The translation dictionary must stay complete.

A missing key does not throw — it renders `undefined` in the middle of the
page — so the only way to catch it is to compare the languages against each
other. Node evaluates the real file rather than a regex approximation of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

I18N_JS = Path(__file__).resolve().parent.parent / "site" / "i18n.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def load() -> dict:
    script = f"""
      {I18N_JS.read_text(encoding="utf-8")}
      console.log(JSON.stringify({{i18n: I18N, compare: COMPARE_LABELS,
                                  fallback: DEFAULT_LANG}}));
    """
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def bundle() -> dict:
    return load()


def test_the_three_advertised_languages_exist(bundle):
    assert set(bundle["i18n"]) == {"he", "ru", "en"}


def test_hebrew_is_the_default(bundle):
    assert bundle["fallback"] == "he"


def test_every_language_has_every_key(bundle):
    reference = set(bundle["i18n"]["he"])
    for lang, table in bundle["i18n"].items():
        missing = reference - set(table)
        extra = set(table) - reference
        assert not missing, f"{lang} is missing {sorted(missing)}"
        assert not extra, f"{lang} has stray keys {sorted(extra)}"


def test_no_value_is_empty(bundle):
    for lang, table in bundle["i18n"].items():
        for key, value in table.items():
            assert isinstance(value, str) and value.strip(), f"{lang}.{key} is empty"


def test_only_hebrew_is_right_to_left(bundle):
    dirs = {lang: table["dir"] for lang, table in bundle["i18n"].items()}
    assert dirs == {"he": "rtl", "ru": "ltr", "en": "ltr"}


def test_each_language_declares_a_usable_locale(bundle):
    for lang, table in bundle["i18n"].items():
        assert table["locale"].startswith(lang), f"{lang} has locale {table['locale']}"


def test_hebrew_strings_actually_contain_hebrew(bundle):
    """Guards against a copy-paste that leaves Russian text under `he`."""
    hebrew = bundle["i18n"]["he"]
    checked = ["title", "tagline", "buy", "currentHeading", "footer"]
    for key in checked:
        assert any("֐" <= ch <= "ת" for ch in hebrew[key]), key


def test_comparison_sites_are_labelled(bundle):
    # publish.py emits exactly these ids; an unlabelled one renders as a slug.
    assert set(bundle["compare"]) >= {"skyscanner", "google", "kiwi"}


def test_python_and_javascript_agree_on_the_comparison_ids(bundle):
    from datetime import date

    from flight_radar.providers.base import comparison_links

    ids = {link["id"] for link in comparison_links("TLV", "ATH", date(2026, 10, 5), None)}
    assert ids <= set(bundle["compare"])
