"""Guard against SQL the deployed runtime cannot parse.

AWS Lambda's python3.11 runtime ships SQLite **3.7.17**, built in 2013. A
developer machine runs 3.45 and accepts anything, so queries using anything
newer pass every local test and then fail in production with nothing but
`near "X": syntax error`. That has already cost two deploy cycles here — once
on a window function, once on UPSERT.

There is no way to reproduce an old engine locally, so this asserts on the
text of the SQL we ship.
"""

from __future__ import annotations

import inspect
import re

import pytest

from flight_radar import storage as storage_module

# (pattern, the SQLite version that introduced it)
FORBIDDEN = [
    (r"\bROW_NUMBER\s*\(", "3.25 window functions"),
    (r"\bRANK\s*\(", "3.25 window functions"),
    (r"\bDENSE_RANK\s*\(", "3.25 window functions"),
    (r"\bNTILE\s*\(", "3.25 window functions"),
    (r"\bLAG\s*\(", "3.25 window functions"),
    (r"\bLEAD\s*\(", "3.25 window functions"),
    (r"\bOVER\s*\(", "3.25 window functions"),
    (r"\bON\s+CONFLICT\b", "3.24 UPSERT"),
    (r"\bWITH\s+RECURSIVE\b", "3.8.3 common table expressions"),
    (r"\bRETURNING\b", "3.35 RETURNING"),
    (r"\bIIF\s*\(", "3.32 IIF"),
    (r"->>", "3.38 JSON operators"),
]

RUNTIME_VERSION = "3.7.17"


def shipped_sql() -> str:
    """Every SQL statement in the storage module, schema included.

    Parsed out of the string literals rather than grepped over the file:
    prose explaining *why* UPSERT is avoided must not read as using it.
    """
    import ast

    tree = ast.parse(inspect.getsource(storage_module))
    verbs = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "PRAGMA")
    statements = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(v in node.value.upper() for v in verbs)
    ]
    return "\n".join(statements)


@pytest.mark.parametrize("pattern,feature", FORBIDDEN)
def test_storage_avoids_features_newer_than_the_runtime(pattern, feature):
    hits = re.findall(pattern, shipped_sql(), flags=re.IGNORECASE)
    assert not hits, (
        f"storage.py uses {feature}, which SQLite {RUNTIME_VERSION} on Lambda "
        f"cannot parse; it will fail only once deployed"
    )


def test_the_guard_would_actually_catch_something():
    """A guard that cannot fail is not a guard."""
    sample = "SELECT ROW_NUMBER() OVER (PARTITION BY a) FROM t"
    assert any(re.search(p, sample, re.IGNORECASE) for p, _ in FORBIDDEN)


def test_upsert_replacement_is_the_portable_form():
    """The rollup has to overwrite by primary key; INSERT OR REPLACE is the
    spelling that predates UPSERT."""
    source = inspect.getsource(storage_module.Storage.refresh_rollups)
    assert "INSERT OR REPLACE" in source
