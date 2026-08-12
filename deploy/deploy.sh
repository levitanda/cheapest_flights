#!/usr/bin/env bash
# Runs on YOUR machine. Ships the committed tree plus your local .env to the
# server over ssh and runs bootstrap.sh there.
#
#   ./deploy/deploy.sh ubuntu@63.183.211.59 ~/.ssh/flight-radar.pem
#
# Only committed files are shipped (git archive), so nothing stray from the
# working tree ends up on the server. .env is sent separately because it is
# gitignored — as it should be.

set -euo pipefail

TARGET=${1:-}
KEY=${2:-}
STAGE_DIR=/tmp/flight-radar-stage

if [[ -z $TARGET ]]; then
    echo "usage: $0 user@host [path/to/key.pem]" >&2
    exit 1
fi

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[[ -n $KEY ]] && SSH_OPTS+=(-i "$KEY")

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    echo "no .env in $(pwd) — copy .env.example and fill in the token first" >&2
    exit 1
fi

if ! git diff --quiet HEAD 2>/dev/null; then
    echo "warning: uncommitted changes will NOT be deployed (git archive ships HEAD)" >&2
fi

echo "==> Staging code on $TARGET"
ssh "${SSH_OPTS[@]}" "$TARGET" "rm -rf $STAGE_DIR && mkdir -p $STAGE_DIR"
git archive --format=tar HEAD | ssh "${SSH_OPTS[@]}" "$TARGET" "tar -x -C $STAGE_DIR"

echo "==> Shipping .env"
# Written with a umask so the secret is never briefly world-readable on disk.
ssh "${SSH_OPTS[@]}" "$TARGET" "umask 077 && cat > $STAGE_DIR/.env" < .env

if [[ -f watchlist.toml ]]; then
    echo "==> Shipping watchlist.toml"
    ssh "${SSH_OPTS[@]}" "$TARGET" "cat > $STAGE_DIR/watchlist.toml" < watchlist.toml
fi

echo "==> Running bootstrap on the server"
ssh "${SSH_OPTS[@]}" -t "$TARGET" "chmod +x $STAGE_DIR/deploy/bootstrap.sh && $STAGE_DIR/deploy/bootstrap.sh"
