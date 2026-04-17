"""Tests for prune_stale — removing DB chunks whose source file vanished."""

from __future__ import annotations

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.ingest import prune_stale
from gnosis_mcp.sqlite_backend import SqliteBackend


async def _mk_backend(tmp_path) -> SqliteBackend:
    cfg = GnosisMcpConfig(database_url=str(tmp_path / "prune.db"), backend="sqlite")
    backend = SqliteBackend(cfg)
    await backend.startup()
    await backend.init_schema()
    return backend


@pytest.mark.asyncio
async def test_prune_removes_missing_files(tmp_path):
    """A doc in the DB whose file was deleted on disk should be pruned."""
    kb = tmp_path / "kb"
    kb.mkdir()
    kept = kb / "kept.md"
    kept.write_text("# Kept\n\nStill here.\n")

    backend = await _mk_backend(tmp_path)
    try:
        await backend.upsert_doc("kept.md", ["Kept body"], title="Kept", category="g")
        await backend.upsert_doc("gone.md", ["Gone body"], title="Gone", category="g")

        report = await prune_stale(backend, str(kb))
        assert report["pruned"] == ["gone.md"]
        assert report["kept"] == 1

        remaining = {d["file_path"] for d in await backend.list_docs()}
        assert remaining == {"kept.md"}
    finally:
        await backend.shutdown()


@pytest.mark.asyncio
async def test_prune_dry_run_does_not_delete(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()

    backend = await _mk_backend(tmp_path)
    try:
        await backend.upsert_doc("gone.md", ["body"], title="Gone", category="g")
        report = await prune_stale(backend, str(kb), dry_run=True)
        assert report["pruned"] == ["gone.md"]
        assert report["dry_run"] is True
        # Still in DB.
        remaining = {d["file_path"] for d in await backend.list_docs()}
        assert remaining == {"gone.md"}
    finally:
        await backend.shutdown()


@pytest.mark.asyncio
async def test_prune_leaves_crawled_urls_by_default(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "local.md").write_text("# Local\n\nbody\n")

    backend = await _mk_backend(tmp_path)
    try:
        await backend.upsert_doc("local.md", ["body"], title="Local", category="g")
        await backend.upsert_doc(
            "https://example.com/docs", ["crawled body"], title="Crawled", category="web"
        )

        report = await prune_stale(backend, str(kb))
        assert report["pruned"] == []
        remaining = {d["file_path"] for d in await backend.list_docs()}
        assert remaining == {"local.md", "https://example.com/docs"}
    finally:
        await backend.shutdown()


@pytest.mark.asyncio
async def test_prune_include_crawled(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()

    backend = await _mk_backend(tmp_path)
    try:
        await backend.upsert_doc("https://example.com/x", ["body"], title="X", category="web")
        report = await prune_stale(backend, str(kb), include_crawled=True)
        assert report["pruned"] == ["https://example.com/x"]
    finally:
        await backend.shutdown()
