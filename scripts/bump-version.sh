#!/usr/bin/env bash
# scripts/bump-version.sh — authoritatively bump gnosis-mcp version everywhere.
#
# Usage:
#   scripts/bump-version.sh 0.11.0
#
# Edits:
#   - pyproject.toml
#   - src/gnosis_mcp/__init__.py
#   - server.json (two fields: top-level .version, .packages[0].version)
#   - marketplace.json (.plugins[0].version)
#   - SECURITY.md (supported version line)
#   - CHANGELOG.md (renames [Unreleased] → [X.Y.Z] — YYYY-MM-DD, adds new [Unreleased])
#   - docs/rest-api.md (example /health response JSON body)
#   - docs/show-hn.md (leading "Numbers: vX.Y.Z" line)
#   - demo/hero.tape (fake install output line)
#   - skills/setup/SKILL.md (version floor hint)
#   - pkg/arch/PKGBUILD (pkgver + pkgrel=1; sha256 stays stale, see PHASE-B)
#   - pkg/arch/.SRCINFO (regenerated from PKGBUILD if makepkg is installed)
#   - llms.txt / llms-full.txt (warning only — body references left for manual review)
#   - uv.lock (via `uv sync`)
#
# Does NOT touch:
#   - Historical benchmark docs ("captured on v0.10.13" — that's measured-at, not current)
#   - docs/plans/*.md (frozen historical plans)
#   - articles/ (blog drafts; should live in .internal/)
#   - External repo gnosismcp.com (has its own deploy pipeline; see RELEASING.md §7)
#
# Phase B — post-PyPI-resolve steps (require PyPI upload to complete first):
#   - pkg/arch/PKGBUILD sha256sums → run `scripts/update-arch-sums.sh` after tag push
#
# After success:
#   1. Review `git diff`
#   2. Run tests: `uv run pytest -x`
#   3. Run parity: `scripts/check-versions.sh`
#   4. Commit + tag + push (see `scripts/release.sh` for the full flow)

set -euo pipefail

# ---- input validation -----------------------------------------------------
if [[ $# -lt 1 ]]; then
  echo "usage: scripts/bump-version.sh <NEW_VERSION>" >&2
  echo "example: scripts/bump-version.sh 0.11.0" >&2
  exit 2
fi

NEW="$1"

# SemVer regex: accepts MAJOR.MINOR.PATCH plus optional pre-release like -alpha.1
if [[ ! "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9\.]+)?$ ]]; then
  echo "ERROR: '$NEW' is not a valid SemVer string (MAJOR.MINOR.PATCH[-prerelease])" >&2
  exit 2
fi

cd "$(dirname "$0")/.."

# ---- state snapshot -------------------------------------------------------
OLD=$(grep -E '^version = ' pyproject.toml | head -1 | sed 's/version = "\(.*\)"/\1/')
if [[ -z "$OLD" ]]; then
  echo "ERROR: couldn't parse current version from pyproject.toml" >&2
  exit 1
fi

if [[ "$OLD" == "$NEW" ]]; then
  echo "ERROR: pyproject.toml is already at $NEW — nothing to bump" >&2
  echo "  (re-running bump on the same version would duplicate CHANGELOG entries)" >&2
  exit 1
fi

TODAY=$(date +%Y-%m-%d)
# XY of X.Y.Z — for SECURITY.md "latest X.Y.x patch receives security fixes"
NEW_XY=$(echo "$NEW" | cut -d. -f1,2)

echo "bump: $OLD → $NEW  (SECURITY line: latest $NEW_XY.x)"
echo "date: $TODAY"
echo ""

# ---- 1. pyproject.toml ----------------------------------------------------
sed -i -E "s/^version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml
echo "✓ pyproject.toml"

# ---- 2. src/gnosis_mcp/__init__.py ---------------------------------------
sed -i -E "s/^__version__ = \"$OLD\"/__version__ = \"$NEW\"/" src/gnosis_mcp/__init__.py
echo "✓ src/gnosis_mcp/__init__.py"

# ---- 3. server.json (2 fields) -------------------------------------------
python3 - <<PY
import json, sys
path = "server.json"
d = json.load(open(path))
d["version"] = "$NEW"
for p in d.get("packages", []):
    p["version"] = "$NEW"
open(path, "w").write(json.dumps(d, indent=2) + "\n")
PY
echo "✓ server.json"

# ---- 4. marketplace.json --------------------------------------------------
python3 - <<PY
import json
path = "marketplace.json"
d = json.load(open(path))
for p in d.get("plugins", []):
    p["version"] = "$NEW"
open(path, "w").write(json.dumps(d, indent=2) + "\n")
PY
echo "✓ marketplace.json"

# ---- 5. SECURITY.md supported-versions line ------------------------------
OLD_XY=$(echo "$OLD" | cut -d. -f1,2)
if [[ -f SECURITY.md ]]; then
  sed -i -E "s/latest $OLD_XY\.x/latest $NEW_XY.x/g" SECURITY.md
  echo "✓ SECURITY.md"
fi

# ---- 6. CHANGELOG.md ------------------------------------------------------
# Turn [Unreleased] into [X.Y.Z] — YYYY-MM-DD and insert a fresh [Unreleased]
# at the top. If no [Unreleased] section exists, inject one with the new version.
if [[ -f CHANGELOG.md ]]; then
  python3 - <<PY
import re, sys
path = "CHANGELOG.md"
src = open(path).read()

unreleased_re = re.compile(r"^## \[Unreleased\][^\n]*\n", re.M)
if unreleased_re.search(src):
    # Rename existing [Unreleased] → [NEW] - today, then prepend fresh [Unreleased]
    src = unreleased_re.sub(
        f"## [Unreleased]\n\n### Added\n### Changed\n### Fixed\n### Security\n\n## [$NEW] - $TODAY\n", src, count=1
    )
else:
    # No [Unreleased] — inject a new section header after the first H1
    src = re.sub(
        r"^(# [^\n]*\n+)",
        rf"\\1\n## [Unreleased]\n\n### Added\n### Changed\n### Fixed\n### Security\n\n## [$NEW] - $TODAY\n\n",
        src, count=1, flags=re.M,
    )

open(path, "w").write(src)
PY
  echo "✓ CHANGELOG.md ([Unreleased] → [$NEW] - $TODAY)"
fi

# ---- 7a. docs/rest-api.md example response --------------------------------
if [[ -f docs/rest-api.md ]]; then
  sed -i -E "s/\"version\": \"$OLD\"/\"version\": \"$NEW\"/g" docs/rest-api.md
  echo "✓ docs/rest-api.md"
fi

# ---- 7b. docs/show-hn.md leading "Numbers: vX.Y.Z" ------------------------
if [[ -f docs/show-hn.md ]]; then
  sed -i -E "s/Numbers: v$OLD/Numbers: v$NEW/g" docs/show-hn.md
  echo "✓ docs/show-hn.md"
fi

# ---- 7c. demo/hero.tape fake install output -------------------------------
if [[ -f demo/hero.tape ]]; then
  sed -i -E "s/gnosis-mcp-$OLD/gnosis-mcp-$NEW/g" demo/hero.tape
  echo "✓ demo/hero.tape (tape updated — re-record with \`vhs demo/hero.tape\`)"
fi

# ---- 7d. skills/setup/SKILL.md version floor ------------------------------
if [[ -f skills/setup/SKILL.md ]]; then
  sed -i -E "s/≥ $OLD/≥ $NEW/g" skills/setup/SKILL.md
  echo "✓ skills/setup/SKILL.md"
fi

# ---- 7e. pkg/arch/PKGBUILD + .SRCINFO -------------------------------------
# Bump pkgver and reset pkgrel=1. The sha256sums line stays pointing at the
# OLD release because the new tarball only exists on PyPI after publish.yml
# completes. scripts/update-arch-sums.sh finalizes this in Phase B.
if [[ -f pkg/arch/PKGBUILD ]]; then
  sed -i -E "s/^pkgver=$OLD/pkgver=$NEW/" pkg/arch/PKGBUILD
  sed -i -E "s/^pkgrel=[0-9]+/pkgrel=1/" pkg/arch/PKGBUILD
  echo "✓ pkg/arch/PKGBUILD (pkgver=$NEW, pkgrel=1 — run scripts/update-arch-sums.sh after PyPI resolves)"

  if command -v makepkg &>/dev/null; then
    (cd pkg/arch && makepkg --printsrcinfo > .SRCINFO 2>/dev/null) && \
      echo "✓ pkg/arch/.SRCINFO (regenerated)"
  else
    # Fallback: direct sed on the tracked .SRCINFO so it doesn't drift
    if [[ -f pkg/arch/.SRCINFO ]]; then
      sed -i -E "s/^(\tpkgver) = $OLD/\1 = $NEW/" pkg/arch/.SRCINFO
      sed -i -E "s/gnosis_mcp-$OLD/gnosis_mcp-$NEW/g" pkg/arch/.SRCINFO
      sed -i -E "s/python-gnosis-mcp-$OLD/python-gnosis-mcp-$NEW/g" pkg/arch/.SRCINFO
      echo "✓ pkg/arch/.SRCINFO (sed fallback — install \`pacman-contrib\` to use makepkg)"
    fi
  fi
fi

# ---- 8. llms.txt / llms-full.txt (template-rendered) ----------------------
# Rendered from llms.txt.tmpl + llms-full.txt.tmpl with tokens:
#   {{VERSION}}, {{TEST_COUNT}}, {{MCP_MEAN_MS}}, {{MCP_P95_MS}}
# VERSION comes from pyproject.toml (just bumped above). Benchmark numbers
# are preserved from the current committed llms.txt unless overridden via
# GNOSIS_RENDER_MCP_MEAN_MS / GNOSIS_RENDER_MCP_P95_MS / GNOSIS_RENDER_TEST_COUNT.
if [[ -f llms.txt.tmpl ]]; then
  if command -v python3 &>/dev/null; then
    python3 scripts/render-llms.py
    echo "✓ llms.txt + llms-full.txt (templated)"
  else
    echo "⚠ python3 missing — skipping llms template render" >&2
  fi
fi

# ---- 8. uv.lock -----------------------------------------------------------
if command -v uv &>/dev/null; then
  echo ""
  echo "regenerating uv.lock …"
  uv sync --quiet
  echo "✓ uv.lock"
else
  echo "⚠ uv not on PATH — skipping uv.lock regeneration; run \`uv sync\` manually"
fi

# ---- 9. parity check ------------------------------------------------------
echo ""
if scripts/check-versions.sh; then
  echo ""
  echo "bump complete: $OLD → $NEW"
else
  echo ""
  echo "ERROR: parity check failed after bump — review and fix" >&2
  exit 1
fi

echo ""
echo "Next steps:"
echo "  git diff                       # review changes"
echo "  uv run pytest -x               # run tests"
echo "  scripts/release.sh $NEW        # commit + tag + push plan"
