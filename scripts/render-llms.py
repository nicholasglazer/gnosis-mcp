#!/usr/bin/env python3
"""Render llms.txt + llms-full.txt from their .tmpl sources.

Tokens resolved (in order of precedence: env var > default):

    {{VERSION}}       — env GNOSIS_RENDER_VERSION, else pyproject.toml
    {{TEST_COUNT}}    — env GNOSIS_RENDER_TEST_COUNT, else `uv run pytest --collect-only`
    {{MCP_MEAN_MS}}   — env GNOSIS_RENDER_MCP_MEAN_MS, else last committed value in llms.txt
    {{MCP_P95_MS}}    — env GNOSIS_RENDER_MCP_P95_MS, else last committed value in llms.txt

Rationale: `VERSION` and `TEST_COUNT` are cheap to recompute on every
bump; the MCP latency numbers are benchmark-derived and come from env
vars supplied by the person running the bench (we don't want
bump-version.sh to spawn pytest + a bench harness). If nothing supplies
them, we keep whatever the committed llms.txt already shows — that way
the render is idempotent and safe.

Usage:
    scripts/render-llms.py                    # write llms.txt + llms-full.txt
    scripts/render-llms.py --check            # diff-only, exits 1 on drift
    MCP_MEAN_MS=8.7 MCP_P95_MS=13.0 scripts/render-llms.py    # override

The `--check` mode is what CI uses to ensure committed files match the
templates + current pyproject version.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    (ROOT / "llms.txt.tmpl", ROOT / "llms.txt"),
    (ROOT / "llms-full.txt.tmpl", ROOT / "llms-full.txt"),
]


def pyproject_version() -> str:
    for line in (ROOT / "pyproject.toml").read_text().splitlines():
        m = re.match(r'^version *= *"([^"]+)"', line)
        if m:
            return m.group(1)
    raise RuntimeError("couldn't parse version from pyproject.toml")


def pytest_test_count() -> str | None:
    """Try `uv run pytest --collect-only -q`; return None on any failure."""
    for cmd in (
        ["uv", "run", "pytest", "--collect-only", "-q"],
        ["pytest", "--collect-only", "-q"],
    ):
        try:
            out = subprocess.run(
                cmd, cwd=ROOT, capture_output=True, text=True, timeout=60
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"(\d+) tests? collected", out.stdout + out.stderr)
        if m:
            return m.group(1)
    return None


def existing_token(path: Path, pattern: str) -> str | None:
    """Extract a value from the currently-committed rendered file."""
    if not path.exists():
        return None
    m = re.search(pattern, path.read_text())
    return m.group(1) if m else None


def resolve_tokens() -> dict[str, str]:
    version = os.environ.get("GNOSIS_RENDER_VERSION") or pyproject_version()

    test_count = os.environ.get("GNOSIS_RENDER_TEST_COUNT") or pytest_test_count()
    if not test_count:
        # Fall back to whatever's in the current llms.txt
        test_count = existing_token(ROOT / "llms.txt", r"(\d+) tests,") or "0"

    mean_ms = (
        os.environ.get("GNOSIS_RENDER_MCP_MEAN_MS")
        or existing_token(ROOT / "llms.txt", r"([0-9.]+) ms mean")
        or "8.7"
    )
    p95_ms = (
        os.environ.get("GNOSIS_RENDER_MCP_P95_MS")
        or existing_token(ROOT / "llms.txt", r"([0-9.]+) ms p95")
        or "13.0"
    )

    return {
        "VERSION": version,
        "TEST_COUNT": test_count,
        "MCP_MEAN_MS": mean_ms,
        "MCP_P95_MS": p95_ms,
    }


def render(tmpl: str, tokens: dict[str, str]) -> str:
    out = tmpl
    for key, val in tokens.items():
        out = out.replace("{{" + key + "}}", val)
    # Leftover tokens?
    stray = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if stray:
        raise RuntimeError(f"unresolved tokens: {stray}")
    return out


def main() -> int:
    check_only = "--check" in sys.argv
    tokens = resolve_tokens()

    print(f"rendering with: {tokens}")
    drifted: list[str] = []

    for tmpl_path, out_path in TARGETS:
        if not tmpl_path.exists():
            print(f"  skip: {tmpl_path.name} missing")
            continue
        rendered = render(tmpl_path.read_text(), tokens)
        current = out_path.read_text() if out_path.exists() else ""

        if check_only:
            if rendered != current:
                drifted.append(out_path.name)
                print(f"  ✗ {out_path.name} would change")
            else:
                print(f"  ✓ {out_path.name} up to date")
        else:
            if rendered == current:
                print(f"  · {out_path.name} unchanged")
            else:
                out_path.write_text(rendered)
                print(f"  ✓ wrote {out_path.name}")

    if check_only and drifted:
        print("", file=sys.stderr)
        print(
            f"ERROR: {len(drifted)} rendered file(s) drifted from template: {drifted}",
            file=sys.stderr,
        )
        print("  run `scripts/render-llms.py` and commit the result", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
