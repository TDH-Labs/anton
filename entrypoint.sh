#!/usr/bin/env bash
# harbor-sas container entrypoint — config via env:
#   HARBOR_EXECUTOR (default fake), HARBOR_DATA_DIR (default /data), HARBOR_PORT (default 8799)
set -euo pipefail
HARBOR_EXECUTOR="${HARBOR_EXECUTOR:-fake}"
HARBOR_DATA_DIR="${HARBOR_DATA_DIR:-/data}"
HARBOR_PORT="${HARBOR_PORT:-8799}"
mkdir -p "$HARBOR_DATA_DIR"
# provision on first boot (idempotent)
harbor setup --install-dir "$(dirname "$HARBOR_DATA_DIR")" --executor "$HARBOR_EXECUTOR" >/dev/null || true
echo "harbor-sas: executor=$HARBOR_EXECUTOR data=$HARBOR_DATA_DIR port=$HARBOR_PORT"
exec harbor serve --data-dir "$HARBOR_DATA_DIR" --executor "$HARBOR_EXECUTOR" --port "$HARBOR_PORT"
