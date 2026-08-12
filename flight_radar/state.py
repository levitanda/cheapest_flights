"""Keeping the price history alive between stateless invocations.

Lambda gives you a blank /tmp and nothing else, so the SQLite file and the
airport reference tables have to be fetched at the start of a run and put back
at the end. That round-trip is the only thing a long-running server was really
providing.

Correctness rests on there being exactly one writer. A single scheduled
invocation satisfies that; running two concurrently would have the second
overwrite the first's observations, which is why the EventBridge rule must
stay at one scheduled job and the function's reserved concurrency is 1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class S3State:
    def __init__(self, bucket: str, prefix: str, data_dir: Path | str, client=None) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.data_dir = Path(data_dir)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def _key(self, relative: Path) -> str:
        return f"{self.prefix}/{relative.as_posix()}"

    def pull(self) -> int:
        """Restore the data directory from S3. Returns the file count.

        A missing prefix is the normal first run, not an error.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        restored = 0
        try:
            pages = self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=f"{self.prefix}/"
            )
            for page in pages:
                for obj in page.get("Contents", []):
                    relative = obj["Key"][len(self.prefix) + 1 :]
                    if not relative or relative.endswith("/"):
                        continue
                    target = self.data_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self.client.download_file(self.bucket, obj["Key"], str(target))
                    restored += 1
        except Exception as exc:
            logger.warning("state pull failed (starting from empty): %s", exc)
            return 0

        logger.info("state: restored %d file(s) from s3://%s/%s", restored, self.bucket, self.prefix)
        return restored

    def push(self, db_name: str = "flight_radar.sqlite3") -> int:
        """Persist the data directory back to S3.

        The database is always written. Reference tables are only written when
        absent remotely: they are a few megabytes, change a couple of times a
        year, and re-uploading them on every run would be pure waste.
        """
        pushed = 0
        for path in sorted(self.data_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.data_dir)
            key = self._key(relative)
            is_db = path.name.startswith(db_name)

            if not is_db and self._exists(key):
                continue
            try:
                self.client.upload_file(str(path), self.bucket, key)
                pushed += 1
            except Exception as exc:
                # Losing the cache is survivable; losing the database is not.
                if is_db:
                    raise
                logger.warning("state push skipped %s: %s", key, exc)

        logger.info("state: pushed %d file(s) to s3://%s/%s", pushed, self.bucket, self.prefix)
        return pushed

    def _exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def state_from(settings, client=None) -> Optional[S3State]:
    if not settings.state_bucket:
        return None
    return S3State(settings.state_bucket, settings.state_prefix, settings.data_dir, client)
