"""AWS Lambda entry point.

One invocation is one `scan`: pull state from S3, sweep the watchlist, alert,
publish the site payload, push state back. EventBridge provides the schedule
that `watch` mode used to provide itself.

The handler is deliberately thin — everything it calls is the same code the
CLI runs, so a local `python -m flight_radar scan` exercises the identical
path.
"""

from __future__ import annotations

import json
import logging
import os

from .config import Settings
from .geo import Geo
from .notify import build_notifiers
from .providers.travelpayouts import TravelpayoutsProvider
from .publish import build_payload, publisher_from
from .runner import run_scan
from .state import state_from
from .storage import Storage
from .watchlist import load as load_watchlist

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _watchlist_path(settings: Settings):
    """Prefer a watchlist baked into the deployment package.

    Falls back to the built-in TLV sweep, so a package shipped without one
    still does something useful rather than nothing.
    """
    packaged = os.path.join(os.path.dirname(os.path.dirname(__file__)), "watchlist.toml")
    return packaged if os.path.exists(packaged) else settings.watchlist_path


def handler(event, context):  # noqa: ARG001 - Lambda signature
    settings = Settings.from_env()
    settings.ensure_dirs()

    if not settings.tp_token:
        # Fail loudly: a silent no-op run would look healthy in CloudWatch.
        raise RuntimeError("TRAVELPAYOUTS_TOKEN is not configured")

    state = state_from(settings)
    if state:
        state.pull()

    storage = Storage(settings.db_path)
    geo = Geo(settings.cache_dir)
    provider = TravelpayoutsProvider(
        token=settings.tp_token,
        currency=settings.currency,
        marker=settings.tp_marker,
        timeout=settings.http_timeout,
    )
    entries = load_watchlist(_watchlist_path(settings))
    notifiers = build_notifiers(settings, geo)

    report = run_scan(settings, provider, storage, entries, notifiers, geo=geo)

    removed = storage.prune(settings.keep_history_days)
    if removed:
        logger.info("pruned %d stale observations", removed)

    publisher = publisher_from(settings)
    published = bool(publisher and publisher.publish(build_payload(storage, geo, settings.currency, marker=settings.tp_marker)))

    storage.close()
    if state:
        # After the database is closed, so the file on disk is complete.
        state.push()

    result = {
        "offers_seen": report.offers_seen,
        "offers_stored": report.offers_stored,
        "candidates": report.candidates,
        "alerted": report.alerted,
        "suppressed": report.suppressed,
        "published": published,
        "errors": report.errors[:10],
    }
    logger.info("scan complete: %s", json.dumps(result, ensure_ascii=False))
    return result
