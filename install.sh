#!/usr/bin/env bash
# harbor-sas installer — primary packaging (Q3). Installs into $HARBOR_HOME.
set -euo pipefail

HARBOR_HOME="${HARBOR_HOME:-$HOME/.harbor}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

echo "==> harbor-sas install -> $HARBOR_HOME"
mkdir -p "$HARBOR_HOME"

# Preflight: the package requires Python >= 3.11. Fail loudly BEFORE creating a
# venv, with instructions — a 3.10 venv later bricks the install (clean-box
# finding 2026-08-18). Override via PYTHON=python3.11 if 3.11+ isn't the default.
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "ERROR: harbor-sas requires Python >= 3.11."
  echo "  Your '$PYTHON' is: $("$PYTHON" --version 2>&1 || echo unknown)"
  echo "  Retry with:  PYTHON=python3.11 bash install.sh   (install python3.11 first if needed)"
  exit 1
fi

# Rebuild if an existing venv was built with the wrong interpreter (stale venv
# trap: a prior run with a 3.10 default leaves a venv that fails version checks).
if [ -x "$HARBOR_HOME/venv/bin/python" ] && \
   ! "$HARBOR_HOME/venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "==> existing venv uses Python < 3.11 — rebuilding"
  rm -rf "$HARBOR_HOME/venv"
fi
if [ ! -x "$HARBOR_HOME/venv/bin/harbor" ]; then
  "$PYTHON" -m venv "$HARBOR_HOME/venv"
fi
"$HARBOR_HOME/venv/bin/pip" install -q --disable-pip-version-check -e "$REPO_DIR"
# 4. Check for Agent Canvas UI
CANVAS_BIN="$(which agent-canvas 2>/dev/null || echo "$HOME/.local/bin/agent-canvas")"
if [ -x "$CANVAS_BIN" ]; then
  echo "==> Agent Canvas UI detected at: $CANVAS_BIN"
else
  echo "==> Agent Canvas UI not found. Install globally via: npm install -g @openhands/agent-canvas"
fi

echo "==> Installed successfully. Start the turnkey system with:"
echo "    1. Control Plane & 3D Neural Graph:  $HARBOR_HOME/venv/bin/harbor dashboard --data-dir $HARBOR_HOME/data"
echo "    2. Background Automation Engine:     $HARBOR_HOME/venv/bin/harbor serve --data-dir $HARBOR_HOME/data"
echo "    3. Agent Canvas Multi-Panel UI:      agent-canvas --port 8000"