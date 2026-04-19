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

# ---- .claude-plugin/plugin.json ------------------------------------------
if [[ -f .claude-plugin/plugin.json ]]; then
  PLUGIN=$(python -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])")
  echo "plugin.json:         $PLUGIN"
  [[ "$PYPROJECT" != "$PLUGIN" ]] && fail ".claude-plugin/plugin.json: $PLUGIN ≠ $PYPROJECT"
fi

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
  # URL drift: PKGBUILD and .SRCINFO must point at the same PyPI URL.
  # Content-hash paths from old releases silently persist if only sha256 gets
  # updated (happened v0.11.1 → v0.11.2). Enforce the predictable /source/g/
  # PyPI path in both files.
  if [[ -f pkg/arch/PKGBUILD ]]; then
    PKGBUILD_URL=$(grep -oE 'https://files\.pythonhosted\.org/packages/[^"]+' pkg/arch/PKGBUILD | head -1)
    SRCINFO_URL=$(grep -oE 'https://files\.pythonhosted\.org/packages/[^[:space:]]+' pkg/arch/.SRCINFO | head -1)
    # Normalize: expand PKGBUILD's $pkgver shell var to the actual version so we
    # can compare to .SRCINFO's literal expansion.
    PKGBUILD_URL_EXPANDED="${PKGBUILD_URL//\$pkgver/$PYPROJECT}"
    if [[ -n "$PKGBUILD_URL_EXPANDED" && -n "$SRCINFO_URL" && "$PKGBUILD_URL_EXPANDED" != "$SRCINFO_URL" ]]; then
      fail "PKGBUILD and .SRCINFO disagree on source URL (drift).
  PKGBUILD (expanded): $PKGBUILD_URL_EXPANDED
  .SRCINFO:            $SRCINFO_URL
  Regenerate with: (cd pkg/arch && makepkg --printsrcinfo > .SRCINFO)"
    fi
    # Both should use the predictable /source/g/ path, not a content-hash path.
    if [[ -n "$PKGBUILD_URL" && "$PKGBUILD_URL" != *"/source/g/gnosis-mcp/"* ]]; then
      fail "PKGBUILD source URL is not the predictable /source/g/gnosis-mcp/ form — $PKGBUILD_URL"
    fi
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
