#!/usr/bin/env bash
# scripts/release.sh — orchestrate a gnosis-mcp release end-to-end.
#
# Usage:
#   scripts/release.sh 0.11.0
#
# What it does:
#   1. Pre-flight — working tree clean, on main, no stray changes
#   2. Runs scripts/bump-version.sh to edit every version-bearing file
#   3. Runs the test suite (pytest -x)
#   4. Runs scripts/check-versions.sh for parity
#   5. Shows the diff, asks for human confirmation
#   6. Commits "release: vX.Y.Z" and tags vX.Y.Z (annotated)
#   7. Prints the push plan for all three remotes (selify/codeberg/github)
#
# What it does NOT do:
#   - Push anywhere (user runs git push explicitly per RELEASING.md)
#   - Update the gnosismcp.com website (separate repo, separate deploy —
#     see RELEASING.md for that pipeline)
#   - Build/publish PyPI or GHCR (triggered automatically by the tag
#     push via .github/workflows/publish.yml and .github/workflows/docker.yml)

set -euo pipefail

cd "$(dirname "$0")/.."

# ---- input validation -----------------------------------------------------
if [[ $# -lt 1 ]]; then
  echo "usage:" >&2
  echo "  scripts/release.sh <NEW_VERSION>         # full release flow" >&2
  echo "  scripts/release.sh verify <VERSION>      # probe registries for a pushed version" >&2
  exit 2
fi

# ---- verify subcommand ----------------------------------------------------
# Usage: scripts/release.sh verify 0.11.0
# Probes every downstream registry and prints a green/yellow/red table.
# Safe to re-run; makes no changes.
if [[ "$1" == "verify" ]]; then
  if [[ $# -lt 2 ]]; then
    echo "usage: scripts/release.sh verify <VERSION>" >&2
    exit 2
  fi
  VER="$2"
  VER="${VER#v}"
  TAG="v$VER"

  probe() {
    local label="$1" url="$2"
    if curl -fsSI -o /dev/null --max-time 10 "$url" 2>/dev/null; then
      printf '  %-20s %s  \033[32m✓ live\033[0m\n' "$label" "$url"
    else
      printf '  %-20s %s  \033[33m… not yet\033[0m\n' "$label" "$url"
    fi
  }

  probe_json() {
    local label="$1" url="$2" jq_expr="$3" expect="$4"
    local body
    body=$(curl -fsS --max-time 10 "$url" 2>/dev/null || true)
    if [[ -z "$body" ]]; then
      printf '  %-20s %s  \033[33m… not yet\033[0m\n' "$label" "$url"
      return
    fi
    local got
    got=$(echo "$body" | jq -r "$jq_expr" 2>/dev/null || true)
    if [[ "$got" == "$expect" ]]; then
      printf '  %-20s %s  \033[32m✓ %s\033[0m\n' "$label" "$url" "$got"
    else
      printf '  %-20s %s  \033[33m… got %s\033[0m\n' "$label" "$url" "${got:-none}"
    fi
  }

  echo "━━━ verifying downstream registries for v$VER ━━━━━━━━━━━━━━━━━━━━"
  echo ""

  probe "PyPI sdist"     "https://files.pythonhosted.org/packages/source/g/gnosis-mcp/gnosis_mcp-${VER}.tar.gz"
  probe "PyPI wheel"     "https://pypi.org/pypi/gnosis-mcp/${VER}/json"
  probe "GHCR manifest"  "https://github.com/nicholasglazer/gnosis-mcp/pkgs/container/gnosis-mcp"
  probe "GitHub Release" "https://github.com/nicholasglazer/gnosis-mcp/releases/tag/${TAG}"
  probe "GitHub tag"     "https://github.com/nicholasglazer/gnosis-mcp/tree/${TAG}"

  if command -v jq &>/dev/null; then
    probe_json "MCP Registry" \
      "https://registry.modelcontextprotocol.io/v0/servers?search=gnosis-mcp" \
      '.servers[]?|select(.name|test("gnosis-mcp"))|.version' \
      "$VER"
  else
    probe "MCP Registry"   "https://registry.modelcontextprotocol.io/v0/servers?search=gnosis-mcp"
    echo "  (install jq for MCP Registry version check)"
  fi

  probe "AUR package"    "https://aur.archlinux.org/packages/python-gnosis-mcp"

  echo ""
  echo "Legend: ✓ live = reachable & (where checked) matches v$VER"
  echo "         … not yet = workflow may still be running, or not published yet"
  echo ""
  echo "If something is stuck > 15 min after \`git push github main --tags\`:"
  echo "  https://github.com/nicholasglazer/gnosis-mcp/actions"
  exit 0
fi

NEW="$1"
TAG="v$NEW"

# ---- 1. pre-flight --------------------------------------------------------
echo "→ pre-flight checks"

if [[ ! -d .git ]]; then
  echo "ERROR: not inside a git repo" >&2
  exit 1
fi

BRANCH=$(git symbolic-ref --short HEAD)
if [[ "$BRANCH" != "main" ]]; then
  echo "ERROR: on branch '$BRANCH' — release only from 'main'" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is not clean — commit or stash first" >&2
  git status --short
  exit 1
fi

if git rev-parse "$TAG" &>/dev/null; then
  echo "ERROR: tag $TAG already exists" >&2
  exit 1
fi

echo "  ✓ on main, clean tree, $TAG is free"

# ---- 2. bump versions -----------------------------------------------------
echo ""
echo "→ bumping versions"
scripts/bump-version.sh "$NEW"

# ---- 3. tests -------------------------------------------------------------
echo ""
echo "→ running test suite"
if command -v uv &>/dev/null; then
  uv run pytest -x --no-header -q
else
  pytest -x --no-header -q
fi

# ---- 4. parity ------------------------------------------------------------
echo ""
echo "→ verifying version parity"
scripts/check-versions.sh

# ---- 5. diff + confirmation ----------------------------------------------
echo ""
echo "→ diff summary"
git diff --stat
echo ""
echo "Full diff:"
echo "  git diff"
echo ""
read -rp "Proceed with release commit + tag $TAG? [y/N] " REPLY
if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
  echo "aborted — working tree has edits but nothing committed"
  echo "run 'git restore .' to undo the version bump"
  exit 1
fi

# ---- 6. commit + tag ------------------------------------------------------
echo ""
echo "→ committing + tagging"

# CHANGELOG entry content for the tag annotation
CHANGELOG_ENTRY=$(awk "/^## \\[$NEW\\]/{p=1; next} /^## \\[/{p=0} p" CHANGELOG.md | head -40)

git add -A
git -c commit.gpgsign=false commit -m "release: v$NEW

$CHANGELOG_ENTRY"

git -c commit.gpgsign=false tag -a "$TAG" -m "v$NEW

$CHANGELOG_ENTRY"

echo "  ✓ commit + tag $TAG created"

# ---- 7. push plan ---------------------------------------------------------
echo ""
echo "━━━ RELEASE READY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Commit + tag are local only. Push manually per the project's"
echo "three-remote policy (per docs/RELEASING.md):"
echo ""
echo "  # Primary (triggers GitHub Actions — PyPI + GHCR + MCP Registry):"
echo "  git push github main --tags"
echo ""
echo "  # Mirrors:"
echo "  git push codeberg main --tags"
echo "  git push selify main --tags    # may fail if SSH not set up — non-critical"
echo ""
echo "After pushing, run this to poll every downstream registry:"
echo ""
echo "  scripts/release.sh verify $NEW"
echo ""
echo "Then update gnosismcp.com separately (see docs/releasing.md §7)."
echo ""
