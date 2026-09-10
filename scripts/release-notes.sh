#!/usr/bin/env bash
# scripts/release-notes.sh — print the CHANGELOG section for a released version.
#
# Usage:
#   scripts/release-notes.sh 0.16.1        # or v0.16.1
#
# Prints that version's section body on stdout, ready for
# `gh release create --notes-file`. Exits 1 when the version has no section, which
# is the signal for publish.yml to fall back to GitHub's generated notes.
#
# Why this exists: `gh release create --generate-notes` only sees merged pull
# requests, so v0.16.0 — a release of roughly twenty fixes landed as direct
# commits — was published as "one PR: exit non-zero when --embed embedded nothing",
# and v0.15.0 listed `github-actions[bot]` as a "New Contributor". The CHANGELOG is
# the accurate record; this gets it onto the Releases page.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "usage: scripts/release-notes.sh <version>" >&2
  exit 2
fi

python3 - "$VERSION" <<'PY'
import pathlib
import re
import sys

want = sys.argv[1].lstrip("v")
path = pathlib.Path("CHANGELOG.md")
if not path.exists():
    sys.exit(1)

lines = path.read_text(encoding="utf-8").splitlines()

start = None
for i, line in enumerate(lines):
    m = re.match(r"^## \[([^\]]+)\]", line)
    if m and m.group(1) == want:
        start = i + 1
        break
if start is None:
    sys.exit(1)

body = []
for line in lines[start:]:
    if re.match(r"^## \[", line):
        break
    body.append(line)

# Group into blocks at each heading so a heading with nothing under it — the
# "### Security" placeholder every entry carries — is dropped rather than
# published as an empty section.
blocks: list[list[str]] = []
for line in body:
    if re.match(r"^#{2,3}\s", line) or not blocks:
        blocks.append([line])
    else:
        blocks[-1].append(line)


def has_content(block: list[str]) -> bool:
    return any(line.strip() and not line.lstrip().startswith("#") for line in block)


text = "\n".join(line for block in blocks if has_content(block) for line in block).strip()
if not text:
    sys.exit(1)

print(text)
PY
