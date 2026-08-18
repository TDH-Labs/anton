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
"$HARBOR_HOME/venv/bin/harbor" setup --install-dir "$HARBOR_HOME"
echo "==> installed. Start it with:"
echo "    $HARBOR_HOME/venv/bin/harbor serve --data-dir $HARBOR_HOME/data --executor fake"
echo "    $HARBOR_HOME/venv/bin/harbor dashboard --data-dir $HARBOR_HOME/data"