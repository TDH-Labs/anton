#!/usr/bin/env bash
# anton container entrypoint — config via env:
#   ANTON_EXECUTOR (default pi), ANTON_DATA_DIR (default /data),
#   ANTON_PORT (dashboard/API port, default 8799), ANTON_SERVE_PORT
#   (scheduler/webhook engine port, default 8798), ANTON_WEB_INTERNAL_PORT
#   (dsh web's own loopback-only port, default 3079), ANTON_WEB_PORT (the
#   container's one published port, default 3080 — served by the auth-gate,
#   not dsh web directly), ANTON_WEB_TOKEN (login password; auto-generated
#   and persisted to the data volume on first boot if unset).
#
# Four processes share this container. `anton dashboard` serves the FastAPI
# /api/* surface anton-studio's apiproxy talks to, and `anton serve` runs the
# cron/webhook scheduler loop; both stay container-internal (apiproxy's Node
# half calls dashboard over a hardcoded localhost:8799, so they must share
# this network namespace — see packages/host/apiproxy/src/index.ts). `dsh
# web` is the anton-studio Ops Center UI itself, and it stays loopback-only
# by its own design (the CLI refuses --host 0.0.0.0 — no auth/TLS on that
# surface, an RCE-capable coding agent). docker/auth-gate.mjs is the only
# process that binds a non-loopback interface: a password-gated reverse
# proxy in front of dsh web, and the container's primary/published process.
#
set -euo pipefail

ANTON_EXECUTOR="${ANTON_EXECUTOR:-pi}"
ANTON_DATA_DIR="${ANTON_DATA_DIR:-/data}"
ANTON_PORT="${ANTON_PORT:-8799}"
ANTON_SERVE_PORT="${ANTON_SERVE_PORT:-8798}"
ANTON_WEB_INTERNAL_PORT="${ANTON_WEB_INTERNAL_PORT:-3079}"
export ANTON_WEB_PORT="${ANTON_WEB_PORT:-3080}"
export ANTON_DATA_DIR

mkdir -p "$ANTON_DATA_DIR"
# provision on first boot (idempotent) — install_dir is the parent of data/, so
# `dirname "$ANTON_DATA_DIR"` recovers the install root the volume mount implies
# (e.g. /data -> install_dir=/, data_dir=/data). Only attempted when that parent
# is writable: as a non-root container user / is read-only, and the serve/dashboard
# startup paths self-seed $ANTON_DATA_DIR anyway, so setup is a no-op nicety here.
SETUP_PARENT="$(dirname "$ANTON_DATA_DIR")"
if [ -w "$SETUP_PARENT" ]; then
  anton setup --install-dir "$SETUP_PARENT" --executor "$ANTON_EXECUTOR" >/dev/null || true
fi

# anton's own config.yaml default is general.host: 0.0.0.0 (config.py) —
# harmless behind Docker bridge isolation with no port published for these,
# but pin to loopback explicitly anyway so dashboard/serve match dsh web's
# posture (never bound beyond this container's own loopback). --config isn't
# a documented flag but is real (cli.py, argparse.SUPPRESS'd, not deprecated).
ANTON_CONTAINER_CONFIG="$ANTON_DATA_DIR/container-config.yaml"
printf 'general:\n  host: 127.0.0.1\n' > "$ANTON_CONTAINER_CONFIG"

echo "anton: executor=$ANTON_EXECUTOR data=$ANTON_DATA_DIR dashboard_port=$ANTON_PORT serve_port=$ANTON_SERVE_PORT web_port=$ANTON_WEB_PORT"

# Scheduler/webhook engine in the background.
anton --config "$ANTON_CONTAINER_CONFIG" serve --data-dir "$ANTON_DATA_DIR" --executor "$ANTON_EXECUTOR" --port "$ANTON_SERVE_PORT" &
SERVE_PID=$!

# Dashboard/API in the background — apiproxy's target, not published itself.
anton --config "$ANTON_CONTAINER_CONFIG" dashboard --data-dir "$ANTON_DATA_DIR" --executor "$ANTON_EXECUTOR" --port "$ANTON_PORT" &
DASH_PID=$!

# Ops Center UI in the background — loopback-only, not published itself.
node /app/anton-studio/apps/cli/lib/bin.js web --port "$ANTON_WEB_INTERNAL_PORT" --no-open &
WEB_PID=$!

# Password-gated reverse proxy — the container's primary process, and the
# only one bound to 0.0.0.0.
ANTON_WEB_INTERNAL_PORT="$ANTON_WEB_INTERNAL_PORT" node /app/docker/auth-gate.mjs &
GATE_PID=$!

# `docker stop` sends TERM: forward it to all four children so none is
# orphaned, then wait for the primary process to actually exit.
trap 'kill -TERM "$SERVE_PID" "$DASH_PID" "$WEB_PID" "$GATE_PID" 2>/dev/null || true' TERM INT
wait "$GATE_PID"
