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

import json
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


def test_cli_check_exits_nonzero_on_uninitialized_db(tmp_path):
    """`gnosis-mcp check` must exit 1 when the schema was never created.

    Regression: the command used to print "Chunks table: does not exist" and
    still exit 0, so it could not gate setup scripts, installers, or CI.
    """
    db = tmp_path / "uninitialized.db"
    env = os.environ.copy()
    env["GNOSIS_MCP_DATABASE_URL"] = f"sqlite:///{db}"
    env["GNOSIS_MCP_BACKEND"] = "sqlite"

    check = subprocess.run(
        [sys.executable, "-m", "gnosis_mcp", "check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert check.returncode == 1, f"expected rc=1, got {check.returncode}: {check.stderr}"
    assert "Chunks table: does not exist" in check.stderr
    assert "Run `gnosis-mcp init-db` to create tables." in check.stderr
    assert "unhealthy" in check.stderr


def test_cli_check_exits_nonzero_when_backend_cannot_start(tmp_path):
    """A backend that cannot be opened is unhealthy too (path is a directory)."""
    env = os.environ.copy()
    env["GNOSIS_MCP_DATABASE_URL"] = f"sqlite:///{tmp_path}"
    env["GNOSIS_MCP_BACKEND"] = "sqlite"

    check = subprocess.run(
        [sys.executable, "-m", "gnosis_mcp", "check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert check.returncode == 1, f"expected rc=1, got {check.returncode}: {check.stderr}"
    assert "Cannot start the sqlite backend" in check.stderr
    assert "unhealthy" in check.stderr


@pytest.mark.asyncio
async def test_serve_flags_reach_mcp_tools(e2e_env):
    """`serve --search-limit-max/--content-preview-chars` must reach the tools.

    The tools read a config built by `from_env()` inside `db.app_lifespan()`,
    which is why the CLI exports the values as env vars. A locally patched
    config object would leave `limit=50` uncapped and the previews full-length.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "gnosis_mcp",
            "serve",
            "--search-limit-max",
            "2",
            "--content-preview-chars",
            "60",
        ],
        env=e2e_env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for i in range(5):
                upsert = await session.call_tool(
                    "upsert_doc",
                    {
                        "path": f"flags/doc{i}.md",
                        "content": (
                            f"# Doc {i}\n\nThe quick brown fox jumps over the lazy dog "
                            f"in document number {i}.\n"
                        ),
                        "title": f"Doc {i}",
                        "category": "flags",
                    },
                )
                assert upsert.content, "upsert returned empty content"

            result = await session.call_tool(
                "search_docs", {"query": "quick brown fox", "limit": 50}
            )
            texts = [c.text for c in result.content if hasattr(c, "text")]
            results = json.loads("\n".join(texts))

            assert isinstance(results, list), f"unexpected search payload: {texts!r}"
            # 5 matching docs, but the CLI capped the limit at 2.
            assert len(results) == 2, f"expected the cap to apply, got {len(results)} results"
            for r in results:
                preview = r.get("content_preview", "")
                assert len(preview) <= 63, f"preview not truncated: {preview!r}"
