#!/usr/bin/env bash
# vendor-diff.sh — show every way anton-studio/ diverges from the pinned
# upstream harness tag. Run before any vendored-file edit and before any
# upstream upgrade (see docs/VENDOR-DIFF.md).
set -euo pipefail

PINNED_TAG="${PINNED_TAG:-dsh-v0.1.0-rc.8}"
UPSTREAM="${UPSTREAM:-https://github.com/deepseek-ai/deepseek-harness.git}"
REF="${1:-$PINNED_TAG}"   # optionally pass any upstream tag/branch/SHA
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STUDIO="$REPO_DIR/anton-studio"
MIRROR="/tmp/dsh-upstream-mirror"

if [ ! -d "$MIRROR/.git" ]; then
  echo "Cloning upstream mirror (one-time, blobless)..."
  git clone --filter=blob:none --no-checkout "$UPSTREAM" "$MIRROR" >/dev/null 2>&1
fi
git -C "$MIRROR" fetch --tags --quiet 2>/dev/null || true
git -C "$MIRROR" checkout -q "$REF" 2>/dev/null || { echo "unknown ref: $REF"; exit 1; }
echo "diffing anton-studio/ against upstream $REF"
echo "(excludes: node_modules, build output, .git, upstream CI/meta)"
echo

diff -rq \
  --exclude=node_modules --exclude=.git --exclude=lib --exclude=dist \
  --exclude=.github --exclude=.agents --exclude=.claude \
  --exclude=.pnpm-store --exclude=tsconfig.tsbuildinfo \
  "$MIRROR" "$STUDIO" || true
