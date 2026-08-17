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
    seller        TEXT,
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
    sent_at       TEXT NOT NULL,
    depart_date   TEXT,
    return_date   TEXT,
    airline       TEXT,
    transfers     INTEGER,
    url           TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_route
    ON alerts (origin, destination, trip_kind, depart_month, sent_at);

-- Rollups. Raw observations arrive at ~4,800 rows a day and the whole
-- database round-trips through S3 on every invocation, so keeping a year of
-- them would mean shipping hundreds of megabytes eight times a day. These two
-- tables hold what the charts and the detector actually need, at a size that
-- stays flat.

-- One row per route per calendar day: the cheapest fare seen that day, which
-- is what "was it a good day to buy" means. Retained long enough to draw a
-- year of history.
CREATE TABLE IF NOT EXISTS daily_price (
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    trip_kind     TEXT NOT NULL,
    currency      TEXT NOT NULL,
    day           TEXT NOT NULL,
    min_price     REAL NOT NULL,
    avg_price     REAL NOT NULL,
    observations  INTEGER NOT NULL,
    PRIMARY KEY (origin, destination, trip_kind, currency, day)
);
CREATE INDEX IF NOT EXISTS idx_daily_route
    ON daily_price (origin, destination, trip_kind, currency, day);

-- Current state rather than history: the cheapest fare on offer for each
-- month of departure. Rebuilt from the raw buffer every scan, so it answers
-- "when is it cheapest to fly" with what you could book today.
CREATE TABLE IF NOT EXISTS month_price (
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    trip_kind     TEXT NOT NULL,
    currency      TEXT NOT NULL,
    depart_month  TEXT NOT NULL,
    min_price     REAL NOT NULL,
    avg_price     REAL NOT NULL,
    observations  INTEGER NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (origin, destination, trip_kind, currency, depart_month)
);
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
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns that CREATE TABLE IF NOT EXISTS cannot add retroactively.

        A database created before these columns existed keeps its old shape
        forever otherwise, and the insert would fail against it.
        """
        obs = {r["name"] for r in self._conn.execute("PRAGMA table_info(observations)")}
        if "seller" not in obs:
            self._conn.execute("ALTER TABLE observations ADD COLUMN seller TEXT")

        existing = {r["name"] for r in self._conn.execute("PRAGMA table_info(alerts)")}
        for column, ddl in (
            ("depart_date", "TEXT"),
            ("return_date", "TEXT"),
            ("airline", "TEXT"),
            ("transfers", "INTEGER"),
            ("url", "TEXT"),
        ):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE alerts ADD COLUMN {column} {ddl}")

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
                o.seller,
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
                seller, source, observed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        # Rolled up on the same write path, so the aggregates can never drift
        # out of step with the raw rows that produced them.
        self.refresh_rollups()
        self._conn.commit()
        return len(rows)

    def refresh_rollups(self) -> None:
        """Recompute both aggregates from the raw buffer.

        Recomputed rather than incremented: the buffer is small (a week), the
        aggregate query is trivial, and an exact rebuild cannot accumulate the
        rounding and double-count errors an incremental update would.
        """
        self._conn.execute(
            """INSERT INTO daily_price
                   (origin, destination, trip_kind, currency, day,
                    min_price, avg_price, observations)
               SELECT origin, destination, trip_kind, currency,
                      substr(observed_at, 1, 10),
                      MIN(price), AVG(price), COUNT(*)
               FROM observations
               GROUP BY origin, destination, trip_kind, currency,
                        substr(observed_at, 1, 10)
               ON CONFLICT (origin, destination, trip_kind, currency, day)
               DO UPDATE SET min_price = excluded.min_price,
                             avg_price = excluded.avg_price,
                             observations = excluded.observations"""
        )

        # Fully rebuilt: a departure month that dropped out of the buffer is no
        # longer bookable at that price, and should stop being advertised.
        self._conn.execute("DELETE FROM month_price")
        self._conn.execute(
            """INSERT INTO month_price
                   (origin, destination, trip_kind, currency, depart_month,
                    min_price, avg_price, observations, updated_at)
               SELECT origin, destination, trip_kind, currency,
                      substr(depart_date, 1, 7),
                      MIN(price), AVG(price), COUNT(*), ?
               FROM observations
               WHERE depart_date IS NOT NULL AND depart_date != ''
               GROUP BY origin, destination, trip_kind, currency,
                        substr(depart_date, 1, 7)""",
            (datetime.now(timezone.utc).isoformat(),),
        )

    def record_alert(self, deal: Deal, url: Optional[str] = None) -> None:
        o = deal.offer
        self._conn.execute(
            """INSERT OR IGNORE INTO alerts
               (fingerprint, origin, destination, trip_kind, depart_month,
                price, currency, baseline, drop_pct, z_score, tier, basis,
                sent_at, depart_date, return_date, airline, transfers, url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                _iso(o.depart_date),
                _iso(o.return_date),
                o.airline,
                o.transfers,
                url,
            ),
        )
        self._conn.commit()

    def prune(self, keep_days: int, keep_rollup_days: int = 400) -> int:
        """Drop the raw buffer past `keep_days`, the rollups past a year-plus.

        Two horizons because they serve different things: raw rows only back
        the "cheapest right now" list and deep-link enrichment, while the
        rollup is the price history a chart draws. Keeping raw for a year is
        what would push the database past what Lambda can move each run.

        Must run after `refresh_rollups`, or a day would be deleted before it
        was ever aggregated.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        cur = self._conn.execute("DELETE FROM observations WHERE observed_at < ?", (cutoff,))
        removed = cur.rowcount

        rollup_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=keep_rollup_days)
        ).strftime("%Y-%m-%d")
        self._conn.execute("DELETE FROM daily_price WHERE day < ?", (rollup_cutoff,))

        self._conn.commit()
        return removed

    # -- reads --------------------------------------------------------------

    def baseline(
        self,
        origin: str,
        destination: str,
        trip_kind: str,
        currency: str,
        window_days: int,
    ) -> Optional[Baseline]:
        """Robust price summary for one route bucket, or None if no history.

        Built from daily minima, not from every raw offer. "The cheapest fare
        available today" is the quantity a reader compares against, so the
        baseline has to be the typical cheapest day — mixing in the expensive
        itineraries from the same sweep would inflate every apparent discount.
        Reading the rollup is also what lets a year of history stay affordable.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime(
            "%Y-%m-%d"
        )
        rows = self._conn.execute(
            """SELECT min_price AS price, day, observations
               FROM daily_price
               WHERE origin = ? AND destination = ? AND trip_kind = ?
                 AND currency = ? AND day >= ?""",
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
            # Raw observations behind the rollup, not the number of daily rows:
            # the reliability gates were tuned against how much data we have
            # seen, and one row per day would silently redefine them.
            sample_size=sum(r["observations"] for r in rows),
            distinct_days=len(rows),
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

    def cheapest_current(self, limit: int = 80, max_age_hours: int = 72) -> list[sqlite3.Row]:
        """The cheapest recently-seen fare per route.

        This is what the site shows before any route has enough history to
        produce a deal. Without it the page would sit empty for a week while
        the scanner quietly collected hundreds of perfectly good fares.

        Written as a join against a grouped subquery rather than
        ROW_NUMBER() OVER (...): the SQLite bundled with the Lambda runtime
        rejects window functions outright, and this form works everywhere.
        The outer GROUP BY collapses ties when two rows share the minimum.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        return self._conn.execute(
            """SELECT o.* FROM observations o
               JOIN (
                   SELECT origin, destination, trip_kind, MIN(price) AS best
                   FROM observations
                   WHERE observed_at >= ?
                   GROUP BY origin, destination, trip_kind
               ) m
                 ON o.origin = m.origin
                AND o.destination = m.destination
                AND o.trip_kind = m.trip_kind
                AND o.price = m.best
               WHERE o.observed_at >= ?
               GROUP BY o.origin, o.destination, o.trip_kind
               ORDER BY o.price ASC
               LIMIT ?""",
            (cutoff, cutoff, limit),
        ).fetchall()

    def month_fares(self, limit: int = 900) -> list[sqlite3.Row]:
        """Cheapest fare per route per month of departure.

        Two jobs at once: the "when is it cheapest to fly" chart, and date
        filtering — with one fare per route the page could only ever match a
        single week of the year.
        """
        return self._conn.execute(
            """SELECT m.*, o.depart_date, o.return_date, o.transfers,
                      o.airline, o.seller, o.deep_link
               FROM month_price m
               LEFT JOIN observations o
                 ON o.origin = m.origin AND o.destination = m.destination
                AND o.trip_kind = m.trip_kind AND o.currency = m.currency
                AND substr(o.depart_date, 1, 7) = m.depart_month
                AND o.price = m.min_price
               GROUP BY m.origin, m.destination, m.trip_kind, m.currency,
                        m.depart_month
               ORDER BY m.min_price ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    def price_history(self, routes: Sequence[tuple[str, str, str]], days: int = 180):
        """Daily minima per route, for the history chart.

        Restricted to the routes actually on the page: a full year for every
        route the radar has ever seen would dwarf the rest of the payload.
        """
        if not routes:
            return {}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        out: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for origin, destination, trip_kind in routes:
            rows = self._conn.execute(
                """SELECT day, min_price FROM daily_price
                   WHERE origin = ? AND destination = ? AND trip_kind = ?
                     AND day >= ?
                   ORDER BY day""",
                (origin, destination, trip_kind, cutoff),
            ).fetchall()
            if rows:
                out[(origin, destination, trip_kind)] = rows
        return out

    def recent_alerts(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM alerts ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
