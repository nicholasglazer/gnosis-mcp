#!/usr/bin/env bash
# scripts/update-arch-sums.sh — Phase B of the Arch packaging flow.
#
# Run AFTER `scripts/release.sh X.Y.Z` has pushed the tag AND publish.yml
# has finished uploading the new sdist to PyPI (verify at
# https://pypi.org/project/gnosis-mcp/#files).
#
# What it does:
#   1. Reads pkgver from pkg/arch/PKGBUILD (already bumped by bump-version.sh)
#   2. Downloads the PyPI sdist for that version (predictable source URL)
#   3. Computes sha256, replaces the old hash in PKGBUILD
#   4. Regenerates .SRCINFO via makepkg if available, else sed fallback
#   5. Prints the AUR commit+push commands for you to run
#
# Usage:
#   scripts/update-arch-sums.sh            # uses current PKGBUILD pkgver
#   scripts/update-arch-sums.sh 0.11.0     # explicit version (defensive)

set -euo pipefail

cd "$(dirname "$0")/.."

PKGBUILD=pkg/arch/PKGBUILD
if [[ ! -f "$PKGBUILD" ]]; then
  echo "ERROR: $PKGBUILD not found" >&2
  exit 1
fi

VER="${1:-}"
if [[ -z "$VER" ]]; then
  VER=$(grep -E '^pkgver=' "$PKGBUILD" | head -1 | sed 's/pkgver=//')
fi

if [[ ! "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "ERROR: invalid version '$VER'" >&2
  exit 2
fi

# Predictable PyPI sdist URL (not the content-hash path — that one is
# unguessable at publish time. Both URLs serve the same bytes.)
URL="https://files.pythonhosted.org/packages/source/g/gnosis-mcp/gnosis_mcp-$VER.tar.gz"

echo "fetching $URL"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

if ! curl -fsSL -o "$TMP/sdist.tar.gz" "$URL"; then
  echo "" >&2
  echo "ERROR: could not fetch $URL" >&2
  echo "  · Did publish.yml finish? Check https://pypi.org/project/gnosis-mcp/#files" >&2
  echo "  · Does pypi list $VER? (may take ~60s after workflow completes)" >&2
  exit 3
fi

NEW_SHA=$(sha256sum "$TMP/sdist.tar.gz" | cut -d' ' -f1)
echo "sha256: $NEW_SHA"

# Replace sha256sums=('…') with the computed hash. Also swap the URL in
# PKGBUILD to the predictable one if it's still on the content-hash path.
OLD_SHA=$(grep -E "^sha256sums=" "$PKGBUILD" | sed -E "s/sha256sums=\('([a-f0-9]+)'\).*/\1/")
if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
  echo "(sha256 already current — nothing to do)"
else
  sed -i -E "s/^sha256sums=\('[a-f0-9]+'\)/sha256sums=('$NEW_SHA')/" "$PKGBUILD"
  echo "✓ PKGBUILD sha256sums"
fi

# Normalize the source URL to the predictable form (idempotent).
sed -i -E \
  "s|source=.*|source=(\"\$pkgname-\$pkgver.tar.gz::https://files.pythonhosted.org/packages/source/g/gnosis-mcp/gnosis_mcp-\$pkgver.tar.gz\")|" \
  "$PKGBUILD"
echo "✓ PKGBUILD source URL (predictable form)"

# Regenerate .SRCINFO
if command -v makepkg &>/dev/null; then
  (cd pkg/arch && makepkg --printsrcinfo > .SRCINFO) && \
    echo "✓ pkg/arch/.SRCINFO (regenerated via makepkg)"
else
  # Sed fallback — keeps .SRCINFO in sync with the fields we edit
  if [[ -f pkg/arch/.SRCINFO ]]; then
    sed -i -E "s/^(\tsha256sums) = [a-f0-9]+/\1 = $NEW_SHA/" pkg/arch/.SRCINFO
    echo "✓ pkg/arch/.SRCINFO (sed fallback — install pacman-contrib for canonical output)"
  fi
fi

echo ""
echo "Arch packaging ready for AUR push. From the AUR repo clone:"
echo ""
echo "  cp pkg/arch/PKGBUILD pkg/arch/.SRCINFO <aur-clone-path>/"
echo "  cd <aur-clone-path>"
echo "  git add PKGBUILD .SRCINFO"
echo "  git commit -m \"bump to $VER\""
echo "  git push aur master"
echo ""
echo "Then commit the in-repo copy back to gnosis-mcp:"
echo ""
echo "  git add pkg/arch/PKGBUILD pkg/arch/.SRCINFO"
echo "  git commit -m \"pkg(arch): sha256 for $VER\""
