"""Runtime configuration, entirely env-driven so the same image runs anywhere.

Only the Travelpayouts token is mandatory. Every threshold has a default that
produces roughly 2-5 alerts a week from TLV — raise `MIN_Z_SCORE` if that is
too chatty; it moves the volume far more than `MIN_DROP_PCT` does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional: the service also runs fine with plain exported env vars
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# Units of the given currency per 1 USD. Only the cold-start distance
# heuristic uses this, and only to decide whether a fare is roughly half of
# what it should be — so a rate that drifts a few percent changes nothing.
# Override with USD_RATE when a currency is missing or the drift matters.
_DEFAULT_USD_RATES = {"usd": 1.0, "eur": 0.92, "ils": 3.70, "gbp": 0.79, "rub": 90.0}


def _usd_rate(currency: str) -> float:
    explicit = os.environ.get("USD_RATE")
    if explicit:
        return float(explicit)
    return _DEFAULT_USD_RATES.get(currency, 1.0)


@dataclass(frozen=True)
class Settings:
    # --- data source -------------------------------------------------------
    tp_token: str
    tp_marker: str
    currency: str
    usd_rate: float
    http_timeout: int
    # Which national market the API prices for. Left unset it defaults to "ru"
    # server-side, which is why a Tel Aviv sweep used to surface Moscow, Sochi
    # and Ufa — and quoted prices no Israeli buyer would be offered.
    market: str
    enrich_limit: int

    # --- storage -----------------------------------------------------------
    data_dir: Path
    keep_history_days: int
    keep_rollup_days: int

    # --- detection ---------------------------------------------------------
    baseline_window_days: int
    min_observations: int
    min_distinct_days: int
    min_drop_pct: float
    min_z_score: float
    cold_start_ratio: float
    error_fare_drop_pct: float

    # --- alerting ----------------------------------------------------------
    alert_cooldown_hours: int
    alert_improve_pct: float
    max_alerts_per_scan: int
    scan_interval_minutes: int

    # --- public website ----------------------------------------------------
    site_bucket: str
    site_data_key: str

    # --- durable state (Lambda has no disk that survives an invocation) -----
    state_bucket: str
    state_prefix: str

    # --- notifiers ---------------------------------------------------------
    telegram_token: str
    telegram_chat_id: str
    pushover_token: str
    pushover_user: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "flight_radar.sqlite3"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def watchlist_path(self) -> Path:
        return Path(os.environ.get("WATCHLIST_FILE", "watchlist.toml"))

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("DATA_DIR", "./data")).expanduser()
        currency = os.environ.get("CURRENCY", "usd").lower()
        return cls(
            tp_token=os.environ.get("TRAVELPAYOUTS_TOKEN", ""),
            tp_marker=os.environ.get("TRAVELPAYOUTS_MARKER", ""),
            currency=currency,
            usd_rate=_usd_rate(currency),
            http_timeout=_i("HTTP_TIMEOUT", 20),
            market=os.environ.get("MARKET", "il").lower(),
            # One API call each, ~0.2s apiece, against a 300s timeout — and
            # the page shows up to 80 destinations, so cover all of them.
            enrich_limit=_i("ENRICH_LIMIT", 90),
            data_dir=data_dir,
            # Raw rows are a short buffer, not the archive. At ~4,800 a day a
            # year of them would be hundreds of megabytes moved through S3
            # eight times daily; the daily rollup is the archive instead.
            keep_history_days=_i("KEEP_HISTORY_DAYS", 7),
            keep_rollup_days=_i("KEEP_ROLLUP_DAYS", 400),
            baseline_window_days=_i("BASELINE_WINDOW_DAYS", 90),
            min_observations=_i("MIN_OBSERVATIONS", 12),
            min_distinct_days=_i("MIN_DISTINCT_DAYS", 6),
            min_drop_pct=_f("MIN_DROP_PCT", 0.35),
            # 3.0 rather than the more obvious 2.5: simulated against 60
            # destinations of pure price noise, 2.5 delivers ~7 alerts a week
            # of background chatter and 3.0 delivers ~3, before any real
            # anomaly is added on top. Volume is far more sensitive to this
            # than to MIN_DROP_PCT, which barely moves it.
            min_z_score=_f("MIN_Z_SCORE", 3.0),
            cold_start_ratio=_f("COLD_START_RATIO", 0.45),
            error_fare_drop_pct=_f("ERROR_FARE_DROP_PCT", 0.70),
            alert_cooldown_hours=_i("ALERT_COOLDOWN_HOURS", 48),
            alert_improve_pct=_f("ALERT_IMPROVE_PCT", 0.15),
            max_alerts_per_scan=_i("MAX_ALERTS_PER_SCAN", 6),
            scan_interval_minutes=_i("SCAN_INTERVAL_MINUTES", 180),
            site_bucket=os.environ.get("SITE_BUCKET", ""),
            site_data_key=os.environ.get("SITE_DATA_KEY", "data/deals.json"),
            state_bucket=os.environ.get("STATE_BUCKET", ""),
            state_prefix=os.environ.get("STATE_PREFIX", "state"),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            pushover_token=os.environ.get("PUSHOVER_APP_TOKEN", ""),
            pushover_user=os.environ.get("PUSHOVER_USER_KEY", ""),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
