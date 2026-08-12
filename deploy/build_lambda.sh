#!/usr/bin/env bash
# Build the Lambda deployment zip at dist/flight-radar-lambda.zip.
#
# boto3 is deliberately NOT bundled: the runtime already provides it, and
# shipping our own would add ~15 MB and risk diverging from the version AWS
# actually runs.

set -euo pipefail

cd "$(dirname "$0")/.."
BUILD=build/lambda
OUT=dist/flight-radar-lambda.zip

rm -rf "$BUILD" && mkdir -p "$BUILD" dist

# Only what the handler imports at runtime.
pip install --quiet --target "$BUILD" requests

cp -r flight_radar "$BUILD/"
cp watchlist.default.toml "$BUILD/watchlist.toml"

# Trim what never runs: caches, test suites and dist-info metadata are dead
# weight in a package that gets uploaded on every deploy.
find "$BUILD" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type d -name 'tests' -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type d -name '*.dist-info' -prune -exec rm -rf {} + 2>/dev/null || true

rm -f "$OUT"
(cd "$BUILD" && zip -qr "../../$OUT" .)

echo "built $OUT ($(du -h "$OUT" | cut -f1))"
