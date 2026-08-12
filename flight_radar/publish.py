"""Export what the radar has found to a JSON file the website reads.

The frontend is deliberately static. All the data it needs fits in a file of a
few tens of kilobytes, so pushing that to S3 after each scan avoids running a
web server, a database connection, or a public port on the box that holds the
price history.

Names are resolved in every site language here rather than in the browser: the
page must not have to fetch anything when the reader flips the switcher.

`build_payload` is a pure function of the database, so it can be tested
without touching S3 or the network.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from .config import Settings
from .geo import SITE_LANGS, Geo
from .providers.base import comparison_links
from .providers.travelpayouts import booking_url
from .storage import Storage

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3


def _clean(value: Any) -> Any:
    """SQLite hands back None for missing columns; keep those out of the JSON."""
    return value if value not in ("", None) else None


def _as_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except (TypeError, ValueError):
        return None


def _names(geo: Optional[Geo], code: str) -> dict[str, str]:
    if geo is None:
        return {lang: code for lang in SITE_LANGS}
    return geo.names(code)


def build_payload(
    storage: Storage,
    geo: Optional[Geo] = None,
    currency: str = "usd",
    deal_limit: int = 500,
    marker: str = "",
) -> dict:
    stats = storage.stats()

    deals = []
    for row in storage.recent_alerts(limit=deal_limit):
        origin, destination = row["origin"], row["destination"]
        depart, ret = _as_date(row["depart_date"]), _as_date(row["return_date"])
        deals.append(
            {
                "origin": origin,
                "destination": destination,
                "origin_names": _names(geo, origin),
                "names": _names(geo, destination),
                "country": geo.country(destination) if geo else "",
                "price": row["price"],
                "currency": row["currency"],
                "baseline": row["baseline"],
                "drop_pct": row["drop_pct"],
                "z_score": row["z_score"],
                "tier": row["tier"],
                "basis": row["basis"],
                "trip_kind": row["trip_kind"],
                "depart_date": _clean(row["depart_date"]),
                "return_date": _clean(row["return_date"]),
                "airline": _clean(row["airline"]),
                "transfers": row["transfers"],
                "sent_at": row["sent_at"],
                "url": _clean(row["url"]),
                "compare": comparison_links(origin, destination, depart, ret),
            }
        )

    current = []
    for row in storage.cheapest_current(limit=80):
        origin, destination = row["origin"], row["destination"]
        depart, ret = _as_date(row["depart_date"]), _as_date(row["return_date"])
        current.append(
            {
                "origin": origin,
                "destination": destination,
                "origin_names": _names(geo, origin),
                "names": _names(geo, destination),
                "country": geo.country(destination) if geo else "",
                "price": row["price"],
                "currency": row["currency"],
                "depart_date": _clean(row["depart_date"]),
                "return_date": _clean(row["return_date"]),
                "nights": row["trip_nights"],
                "transfers": row["transfers"],
                "airline": _clean(row["airline"]),
                "seller": _clean(row["seller"]),
                "observed_at": row["observed_at"],
                # Never null: reconstructed from the route when the API gave
                # no deep link, because "here is the price" without "here is
                # where to buy it" is the failure this service exists to avoid.
                "url": booking_url(origin, destination, depart, ret,
                                   row["deep_link"], marker),
                "exact": bool(row["deep_link"]),
                "compare": comparison_links(origin, destination, depart, ret),
            }
        )

    routes = []
    for row in storage.top_routes(limit=60):
        origin, destination = row["origin"], row["destination"]
        routes.append(
            {
                "origin": origin,
                "destination": destination,
                "names": _names(geo, destination),
                "trip_kind": row["trip_kind"],
                "observations": row["n"],
                "cheapest": row["cheapest"],
                "average": row["avg_price"],
                "currency": row["currency"],
            }
        )

    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": currency,
        "langs": list(SITE_LANGS),
        "stats": {
            "observations": stats["observations"],
            "routes": stats["routes"],
            "alerts": stats["alerts"],
            "first_seen": stats["first_seen"],
        },
        "deals": deals,
        "current": current,
        "routes": routes,
    }


class S3Publisher:
    """Uploads the payload to S3. A failure here must never fail a scan."""

    def __init__(self, bucket: str, key: str, cache_seconds: int = 120) -> None:
        self.bucket = bucket
        self.key = key
        self.cache_seconds = cache_seconds

    def publish(self, payload: dict) -> bool:
        try:
            import boto3
        except ImportError:
            logger.warning("boto3 is not installed; skipping site publish")
            return False

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        try:
            boto3.client("s3").put_object(
                Bucket=self.bucket,
                Key=self.key,
                Body=body,
                ContentType="application/json; charset=utf-8",
                # Short TTL: the page should show a fare found twenty minutes
                # ago, and the file is small enough that revalidating is cheap.
                CacheControl=f"public, max-age={self.cache_seconds}",
            )
        except Exception as exc:
            logger.warning("site publish failed: %s", exc)
            return False

        logger.info("published %d bytes to s3://%s/%s", len(body), self.bucket, self.key)
        return True


def publisher_from(settings: Settings) -> Optional[S3Publisher]:
    if not settings.site_bucket:
        return None
    return S3Publisher(settings.site_bucket, settings.site_data_key)
