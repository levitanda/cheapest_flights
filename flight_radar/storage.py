"""SQLite price history and alert log.

Plain `sqlite3` rather than an ORM: the schema is two tables and the only
interesting query is a windowed aggregate, so an ORM would add a dependency
and hide the one query worth reading.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .models import Baseline, Deal, Offer

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY,
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    trip_kind     TEXT NOT NULL,
    price         REAL NOT NULL,
    currency      TEXT NOT NULL,
    depart_date   TEXT,
    return_date   TEXT,
    trip_nights   INTEGER,
    transfers     INTEGER,
    airline       TEXT,
    deep_link     TEXT,
    source        TEXT NOT NULL,
    observed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_route
    ON observations (origin, destination, trip_kind, currency, observed_at);

CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY,
    fingerprint   TEXT NOT NULL UNIQUE,
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    trip_kind     TEXT NOT NULL,
    depart_month  TEXT,
    price         REAL NOT NULL,
    currency      TEXT NOT NULL,
    baseline      REAL NOT NULL,
    drop_pct      REAL NOT NULL,
    z_score       REAL NOT NULL,
    tier          TEXT NOT NULL,
    basis         TEXT NOT NULL,
    sent_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_route
    ON alerts (origin, destination, trip_kind, depart_month, sent_at);
"""


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile. `sorted_values` must be ascending."""
    if not sorted_values:
        raise ValueError("empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


class Storage:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writes -------------------------------------------------------------

    def record_offers(self, offers: Iterable[Offer]) -> int:
        rows = [
            (
                o.origin,
                o.destination,
                o.trip_kind,
                o.price,
                o.currency,
                _iso(o.depart_date),
                _iso(o.return_date),
                o.trip_nights,
                o.transfers,
                o.airline,
                o.deep_link,
                o.source,
                o.observed_at.isoformat(),
            )
            for o in offers
            if o.price > 0
        ]
        if not rows:
            return 0
        self._conn.executemany(
            """INSERT INTO observations
               (origin, destination, trip_kind, price, currency, depart_date,
                return_date, trip_nights, transfers, airline, deep_link,
                source, observed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def record_alert(self, deal: Deal) -> None:
        o = deal.offer
        self._conn.execute(
            """INSERT OR IGNORE INTO alerts
               (fingerprint, origin, destination, trip_kind, depart_month,
                price, currency, baseline, drop_pct, z_score, tier, basis, sent_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                deal.fingerprint,
                o.origin,
                o.destination,
                o.trip_kind,
                o.depart_month,
                o.price,
                o.currency,
                deal.baseline_price,
                deal.drop_pct,
                deal.z_score,
                deal.tier,
                deal.basis,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def prune(self, keep_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        cur = self._conn.execute("DELETE FROM observations WHERE observed_at < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    # -- reads --------------------------------------------------------------

    def baseline(
        self,
        origin: str,
        destination: str,
        trip_kind: str,
        currency: str,
        window_days: int,
    ) -> Optional[Baseline]:
        """Robust price summary for one route bucket, or None if no history."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        rows = self._conn.execute(
            """SELECT price, substr(observed_at, 1, 10) AS day
               FROM observations
               WHERE origin = ? AND destination = ? AND trip_kind = ?
                 AND currency = ? AND observed_at >= ?""",
            (origin.upper(), destination.upper(), trip_kind, currency.lower(), cutoff),
        ).fetchall()
        if not rows:
            return None

        prices = sorted(r["price"] for r in rows)
        median = statistics.median(prices)
        mad = statistics.median([abs(p - median) for p in prices])
        return Baseline(
            route=f"{origin.upper()}-{destination.upper()}",
            trip_kind=trip_kind,
            currency=currency.lower(),
            median=median,
            mad=mad,
            p10=_percentile(prices, 0.10),
            sample_size=len(prices),
            distinct_days=len({r["day"] for r in rows}),
        )

    def seen_fingerprint(self, fingerprint: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alerts WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return row is not None

    def last_alert_price(
        self,
        origin: str,
        destination: str,
        trip_kind: str,
        depart_month: Optional[str],
        within_hours: int,
    ) -> Optional[float]:
        """Cheapest price we alerted on for this route+month inside the cooldown.

        Returning the cheapest (not the latest) is deliberate: the question the
        caller asks is "is the new fare meaningfully better than anything the
        user has already been told about", and the best prior offer is the bar
        to clear.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
        row = self._conn.execute(
            """SELECT MIN(price) AS best FROM alerts
               WHERE origin = ? AND destination = ? AND trip_kind = ?
                 AND IFNULL(depart_month, '') = IFNULL(?, '')
                 AND sent_at >= ?""",
            (origin.upper(), destination.upper(), trip_kind, depart_month, cutoff),
        ).fetchone()
        return row["best"] if row and row["best"] is not None else None

    def stats(self) -> dict:
        obs = self._conn.execute(
            """SELECT COUNT(*) AS n,
                      COUNT(DISTINCT origin || '-' || destination) AS routes,
                      MIN(observed_at) AS first_seen
               FROM observations"""
        ).fetchone()
        alerts = self._conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()
        return {
            "observations": obs["n"],
            "routes": obs["routes"],
            "first_seen": obs["first_seen"],
            "alerts": alerts["n"],
        }

    def top_routes(self, limit: int = 15) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT origin, destination, trip_kind, COUNT(*) AS n,
                      MIN(price) AS cheapest, AVG(price) AS avg_price, currency
               FROM observations
               GROUP BY origin, destination, trip_kind, currency
               ORDER BY n DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def recent_alerts(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM alerts ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
