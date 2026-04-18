#!/usr/bin/env bash
# Verify every version-bearing file in the repo agrees with pyproject.toml.
# Fails CI (and the release workflow) if any of them drift.
#
# Checks:
#   - src/gnosis_mcp/__init__.py   (__version__)
#   - server.json                   (.version + .packages[0].version)
#   - marketplace.json              (.plugins[0].version)
#   - pkg/arch/PKGBUILD             (pkgver=)
#   - pkg/arch/.SRCINFO             (pkgver = / source tarball filename)
#   - docs/rest-api.md              (example JSON "version": ...)
#   - CHANGELOG.md                  ([X.Y.Z] header exists, or [Unreleased])
set -euo pipefail

cd "$(dirname "$0")/.."

PYPROJECT=$(grep -E '^version' pyproject.toml | head -1 | sed 's/version *= *"\(.*\)"/\1/')

FAILED=0
fail() {
  echo "ERROR: $1" >&2
  FAILED=1
}

# ---- core 4 files --------------------------------------------------------
INIT=$(grep -E '^__version__' src/gnosis_mcp/__init__.py | sed 's/__version__ *= *"\(.*\)"/\1/')
SERVER_TOP=$(python -c "import json; d=json.load(open('server.json')); print(d['version'])")
SERVER_PKG=$(python -c "import json; d=json.load(open('server.json')); print(d['packages'][0]['version'])")
MARKET=$(python -c "import json; d=json.load(open('marketplace.json')); print(d['plugins'][0]['version'])")

echo "pyproject:           $PYPROJECT"
echo "__init__:            $INIT"
echo "server.json (top):   $SERVER_TOP"
echo "server.json (pkg):   $SERVER_PKG"
echo "marketplace.json:    $MARKET"

[[ "$PYPROJECT" != "$INIT"       ]] && fail "__init__.py: $INIT ≠ $PYPROJECT"
[[ "$PYPROJECT" != "$SERVER_TOP" ]] && fail "server.json top: $SERVER_TOP ≠ $PYPROJECT"
[[ "$PYPROJECT" != "$SERVER_PKG" ]] && fail "server.json pkg: $SERVER_PKG ≠ $PYPROJECT"
[[ "$PYPROJECT" != "$MARKET"     ]] && fail "marketplace.json: $MARKET ≠ $PYPROJECT"

# ---- pkg/arch/PKGBUILD ---------------------------------------------------
if [[ -f pkg/arch/PKGBUILD ]]; then
  PKGBUILD=$(grep -E '^pkgver=' pkg/arch/PKGBUILD | head -1 | sed 's/pkgver=//')
  echo "PKGBUILD:            $PKGBUILD"
  [[ "$PYPROJECT" != "$PKGBUILD" ]] && fail "pkg/arch/PKGBUILD pkgver: $PKGBUILD ≠ $PYPROJECT"
fi

# ---- pkg/arch/.SRCINFO ---------------------------------------------------
if [[ -f pkg/arch/.SRCINFO ]]; then
  SRCINFO=$(grep -P '^\tpkgver = ' pkg/arch/.SRCINFO | head -1 | awk -F' = ' '{print $2}')
  echo ".SRCINFO:            $SRCINFO"
  [[ "$PYPROJECT" != "$SRCINFO" ]] && fail "pkg/arch/.SRCINFO pkgver: $SRCINFO ≠ $PYPROJECT"
  if ! grep -qE "gnosis_mcp-$PYPROJECT\.tar\.gz" pkg/arch/.SRCINFO; then
    fail "pkg/arch/.SRCINFO source filename does not mention gnosis_mcp-$PYPROJECT.tar.gz"
  fi
fi

# ---- docs/rest-api.md example JSON --------------------------------------
if [[ -f docs/rest-api.md ]]; then
  RESTAPI=$(grep -oE '"version": "[0-9]+\.[0-9]+\.[0-9]+[^"]*"' docs/rest-api.md | head -1 | sed 's/.*"version": "\(.*\)"/\1/')
  if [[ -n "$RESTAPI" ]]; then
    echo "rest-api.md:         $RESTAPI"
    [[ "$PYPROJECT" != "$RESTAPI" ]] && fail "docs/rest-api.md example: $RESTAPI ≠ $PYPROJECT"
  fi
fi

# ---- CHANGELOG gate ------------------------------------------------------
if ! grep -qE "^## \[$PYPROJECT\]" CHANGELOG.md; then
  if ! grep -qE "^## \[Unreleased\]" CHANGELOG.md; then
    fail "CHANGELOG.md has no [$PYPROJECT] section and no [Unreleased]"
  else
    echo "NOTE: CHANGELOG has no [$PYPROJECT] section — pre-release (Unreleased only)"
  fi
fi

if [[ "$FAILED" != "0" ]]; then
  echo "" >&2
  echo "version drift detected — run scripts/bump-version.sh $PYPROJECT to realign" >&2
  exit 1
fi

echo "OK — all version files agree on $PYPROJECT"
