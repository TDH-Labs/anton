#!/usr/bin/env bash
# harbor-sas installer — primary packaging (Q3). Installs into $HARBOR_HOME.
set -euo pipefail

HARBOR_HOME="${HARBOR_HOME:-$HOME/.harbor}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

echo "==> harbor-sas install -> $HARBOR_HOME"
mkdir -p "$HARBOR_HOME"

if [ ! -x "$HARBOR_HOME/venv/bin/harbor" ]; then
  "$PYTHON" -m venv "$HARBOR_HOME/venv"
fi
"$HARBOR_HOME/venv/bin/pip" install -q --disable-pip-version-check -e "$REPO_DIR"
"$HARBOR_HOME/venv/bin/harbor" setup --install-dir "$HARBOR_HOME"
echo "==> installed. Start it with:"
echo "    $HARBOR_HOME/venv/bin/harbor serve --data-dir $HARBOR_HOME/data --executor fake"
echo "    $HARBOR_HOME/venv/bin/harbor dashboard --data-dir $HARBOR_HOME/data"
