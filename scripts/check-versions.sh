#!/usr/bin/env bash
# Verify that all 4 version-bearing files agree.
# Fails the build if pyproject.toml, __init__.py, server.json, and marketplace.json diverge.
set -euo pipefail

cd "$(dirname "$0")/.."

PYPROJECT=$(grep -E '^version' pyproject.toml | head -1 | sed 's/version *= *"\(.*\)"/\1/')
INIT=$(grep -E '^__version__' src/gnosis_mcp/__init__.py | sed 's/__version__ *= *"\(.*\)"/\1/')
SERVER_TOP=$(python -c "import json; d=json.load(open('server.json')); print(d['version'])")
SERVER_PKG=$(python -c "import json; d=json.load(open('server.json')); print(d['packages'][0]['version'])")
MARKET=$(python -c "import json; d=json.load(open('marketplace.json')); print(d['plugins'][0]['version'])")

echo "pyproject:           $PYPROJECT"
echo "__init__:            $INIT"
echo "server.json (top):   $SERVER_TOP"
echo "server.json (pkg):   $SERVER_PKG"
echo "marketplace.json:    $MARKET"

if [[ "$PYPROJECT" != "$INIT" || "$PYPROJECT" != "$SERVER_TOP" \
   || "$PYPROJECT" != "$SERVER_PKG" || "$PYPROJECT" != "$MARKET" ]]; then
  echo "ERROR: version mismatch across files" >&2
  exit 1
fi

if ! grep -qE "^## \[$PYPROJECT\]" CHANGELOG.md; then
  if ! grep -qE "^## \[Unreleased\]" CHANGELOG.md; then
    echo "ERROR: CHANGELOG.md has no entry for $PYPROJECT or [Unreleased]" >&2
    exit 1
  fi
  echo "NOTE: CHANGELOG has no [$PYPROJECT] entry yet — assuming pre-release (Unreleased)"
fi

echo "OK — all version files agree on $PYPROJECT"
