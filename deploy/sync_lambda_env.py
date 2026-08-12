#!/usr/bin/env python3
"""Push the function's environment from GitHub secrets and variables.

Run by CI so that the repository is the single place configuration lives —
nothing has to be typed into the AWS console, and a redeploy cannot silently
run against stale settings.

Two things make this less trivial than it looks:

* `update-function-configuration` REPLACES the whole variable map rather than
  merging into it. Sending a partial map would wipe the bucket names and leave
  a function that fails on startup, so the full set is always assembled here.

* The AWS CLI's `Variables={k=v,...}` shorthand splits on commas and equals
  signs, which mangles any token containing either. This writes real JSON and
  hands it over as a file instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
FUNCTION = os.environ.get("FUNCTION_NAME", "flight-radar-scan")

# Infrastructure identifiers: not secret, and wrong values here break the run
# in confusing ways, so they are pinned by the workflow rather than guessed.
FIXED = {
    "DATA_DIR": "/tmp/flight-radar",
    "STATE_PREFIX": "state",
    "SITE_DATA_KEY": "data/deals.json",
    "STATE_BUCKET": os.environ.get("STATE_BUCKET", ""),
    "SITE_BUCKET": os.environ.get("SITE_BUCKET", ""),
}

# Forwarded only when non-empty, so an unset tuning variable falls back to the
# default compiled into config.py instead of overriding it with "".
OPTIONAL = (
    "TRAVELPAYOUTS_MARKER",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "PUSHOVER_APP_TOKEN",
    "PUSHOVER_USER_KEY",
    "CURRENCY",
    "USD_RATE",
    "BASELINE_WINDOW_DAYS",
    "MIN_OBSERVATIONS",
    "MIN_DISTINCT_DAYS",
    "MIN_DROP_PCT",
    "MIN_Z_SCORE",
    "COLD_START_RATIO",
    "ERROR_FARE_DROP_PCT",
    "ALERT_COOLDOWN_HOURS",
    "ALERT_IMPROVE_PCT",
    "MAX_ALERTS_PER_SCAN",
    "KEEP_HISTORY_DAYS",
)


def build() -> dict[str, str]:
    token = os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip()
    if not token:
        sys.exit(
            "::error::TRAVELPAYOUTS_TOKEN is not set as a repository secret.\n"
            "Add it under Settings -> Secrets and variables -> Actions -> Secrets.\n"
            "Refusing to deploy a configuration that would blank the existing token."
        )

    missing = [k for k, v in FIXED.items() if not v]
    if missing:
        sys.exit(f"::error::workflow did not supply: {', '.join(missing)}")

    env = dict(FIXED)
    env["TRAVELPAYOUTS_TOKEN"] = token
    for name in OPTIONAL:
        value = os.environ.get(name, "").strip()
        if value:
            env[name] = value
    return env


def main() -> int:
    env = build()

    # Never printed: GitHub masks known secrets in logs, but a value pasted
    # into the wrong secret would not be masked.
    names = sorted(env)
    print(f"syncing {len(names)} variables: {', '.join(names)}")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"Variables": env}, fh)
        path = fh.name

    try:
        subprocess.run(
            ["aws", "lambda", "update-function-configuration",
             "--function-name", FUNCTION, "--region", REGION,
             "--environment", f"file://{path}"],
            check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["aws", "lambda", "wait", "function-updated-v2",
             "--function-name", FUNCTION, "--region", REGION],
            check=True,
        )
    finally:
        os.unlink(path)

    print("configuration synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
