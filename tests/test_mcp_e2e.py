"""End-to-end MCP protocol tests.

Spawns `gnosis-mcp serve` as a subprocess and drives it through the real MCP
protocol (stdio transport). Validates that tools and resources are registered,
callable, and return sensible results.

Marked `e2e` — skipped by default in fast test runs, enabled in CI's full pass.

Run locally:
    uv run pytest tests/test_mcp_e2e.py -v -m e2e

Run without the `e2e` mark to exclude:
    uv run pytest -m "not e2e"
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _MCP_AVAILABLE, reason="mcp client SDK unavailable"),
]


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    """Environment with an isolated SQLite DB, schema initialised, and writable mode."""
    db = tmp_path / "e2e.db"
    env = os.environ.copy()
    env["GNOSIS_MCP_DATABASE_URL"] = f"sqlite:///{db}"
    env["GNOSIS_MCP_WRITABLE"] = "true"
    env["GNOSIS_MCP_BACKEND"] = "sqlite"
    env["GNOSIS_MCP_LOG_LEVEL"] = "WARNING"

    # Pre-initialise the schema so the first search sees the FTS table.
    subprocess.run(
        [sys.executable, "-m", "gnosis_mcp", "init-db"],
        env=env,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return env


@pytest.mark.asyncio
async def test_stdio_tools_and_resources_surface(e2e_env):
    """Spawn the server, list tools, confirm expected names are present."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gnosis_mcp", "serve", "--transport", "stdio"],
        env=e2e_env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            names = {t.name for t in tools_result.tools}
            # Six read tools
            assert {
                "search_docs",
                "get_doc",
                "get_related",
                "get_context",
                "get_graph_stats",
                "search_git_history",
            }.issubset(names), f"missing read tools; got: {sorted(names)}"
            # Three write tools (gated on writable=true)
            assert {"upsert_doc", "delete_doc", "update_metadata"}.issubset(names), (
                f"missing write tools; got: {sorted(names)}"
            )

            resources_result = await session.list_resources()
            uris = {str(r.uri) for r in resources_result.resources}
            assert any("gnosis://docs" in u for u in uris), f"missing docs resource: {uris}"


@pytest.mark.asyncio
async def test_stdio_upsert_then_search_roundtrip(e2e_env):
    """Write a doc through the server, then search for a word from it."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gnosis_mcp", "serve", "--transport", "stdio"],
        env=e2e_env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # First initialise the DB schema via a write
            upsert = await session.call_tool(
                "upsert_doc",
                {
                    "path": "e2e/hello.md",
                    "content": "# Hello\n\nThe quick brown fox jumps over the lazy dog.\n",
                    "title": "Hello",
                    "category": "e2e",
                },
            )
            assert upsert.content, "upsert returned empty content"

            result = await session.call_tool("search_docs", {"query": "quick brown fox"})
            assert result.content, "search returned empty content"
            # MCP packs textual content in a list of content blocks
            texts = [c.text for c in result.content if hasattr(c, "text")]
            joined = "\n".join(texts)
            assert "hello" in joined.lower() or "fox" in joined.lower(), (
                f"expected a match for 'quick brown fox' in: {joined!r}"
            )


def test_cli_check_exits_zero_on_healthy_db(tmp_path):
    """`gnosis-mcp check` should exit 0 against a freshly-initialised SQLite DB."""
    db = tmp_path / "check.db"
    env = os.environ.copy()
    env["GNOSIS_MCP_DATABASE_URL"] = f"sqlite:///{db}"
    env["GNOSIS_MCP_BACKEND"] = "sqlite"

    init = subprocess.run(
        [sys.executable, "-m", "gnosis_mcp", "init-db"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert init.returncode == 0, f"init-db failed: {init.stderr}"

    check = subprocess.run(
        [sys.executable, "-m", "gnosis_mcp", "check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert check.returncode == 0, f"check failed: rc={check.returncode} stderr={check.stderr}"
