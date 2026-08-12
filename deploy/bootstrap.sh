#!/usr/bin/env bash
# Runs ON the server. Idempotent — safe to re-run for every update.
#
# Expects the code to already be staged at $STAGE_DIR (deploy.sh does that),
# and an .env to exist either in the stage or already installed.

set -euo pipefail

APP_DIR=${APP_DIR:-/opt/cheapest_flights}
STAGE_DIR=${STAGE_DIR:-/tmp/flight-radar-stage}
SERVICE=flight-radar
RUN_USER=${RUN_USER:-$(id -un)}

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

if [[ ! -d $STAGE_DIR ]]; then
    echo "staging dir $STAGE_DIR not found — run deploy.sh from your machine" >&2
    exit 1
fi

# Deploys run on every push, so skip the ~20s apt round-trip once the box is
# already provisioned.
if ! dpkg -s python3-venv rsync >/dev/null 2>&1; then
    log "Installing system packages"
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-pip rsync >/dev/null
fi

log "Preparing $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown "$RUN_USER:$RUN_USER" "$APP_DIR"

# data/ holds the accumulated price history — the one thing that must never be
# wiped by a deploy, since the detector goes blind without it.
mkdir -p "$APP_DIR/data"

log "Syncing application code"
# --delete so a file removed from the repo also disappears here, with the
# three stateful paths held back: history, secrets, and the venv.
rsync -a --delete \
      --exclude 'data/' --exclude '.env' --exclude '.venv/' \
      "$STAGE_DIR/" "$APP_DIR/"

if [[ -f $STAGE_DIR/.env ]]; then
    log "Installing .env"
    install -m 600 "$STAGE_DIR/.env" "$APP_DIR/.env"
fi

if [[ ! -f $APP_DIR/.env ]]; then
    echo "no .env at $APP_DIR/.env — the service cannot start without a token" >&2
    exit 1
fi
chmod 600 "$APP_DIR/.env"

log "Building virtualenv"
if [[ ! -x $APP_DIR/.venv/bin/python ]]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

log "Verifying the build"
cd "$APP_DIR"
if ! "$APP_DIR/.venv/bin/python" -m flight_radar doctor; then
    echo
    echo "doctor reported problems — fix .env before the service is useful." >&2
    echo "Continuing so the unit is installed either way." >&2
fi

log "Installing systemd unit"
sudo install -m 644 "$APP_DIR/deploy/flight-radar.service" \
     "/etc/systemd/system/${SERVICE}.service"
sudo sed -i "s|^User=.*|User=${RUN_USER}|" "/etc/systemd/system/${SERVICE}.service"
sudo sed -i "s|^Group=.*|Group=${RUN_USER}|" "/etc/systemd/system/${SERVICE}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" >/dev/null
sudo systemctl restart "$SERVICE"

rm -rf "$STAGE_DIR"

sleep 2
log "Service status"
sudo systemctl --no-pager --lines=15 status "$SERVICE" || true

echo
log "Done. Follow the log with:  journalctl -u ${SERVICE} -f"
