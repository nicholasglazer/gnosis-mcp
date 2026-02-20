"""Tests for server helpers, MCP tools, resources, and webhook."""

import json
import urllib.request

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.db import AppContext
from gnosis_mcp.pg_backend import _row_count, _to_or_query
import gnosis_mcp.server as server_mod
from gnosis_mcp.server import (
    _notify_webhook,
    _split_chunks,
    delete_doc,
    get_doc,
    get_related,
    list_categories,
    list_docs,
    read_doc_resource,
    search_docs,
    update_metadata,
    upsert_doc,
)
from gnosis_mcp.sqlite_backend import SqliteBackend


class TestSplitChunks:
    def test_short_content_single_chunk(self):
        result = _split_chunks("Hello world", max_size=100)
        assert result == ["Hello world"]

    def test_splits_at_paragraph_boundary(self):
        content = "A" * 50 + "\n\n" + "B" * 50
        result = _split_chunks(content, max_size=60)
        assert len(result) == 2
        assert result[0] == "A" * 50
        assert result[1] == "B" * 50

    def test_multiple_chunks(self):
        paragraphs = ["Para " + str(i) + " " + "x" * 40 for i in range(10)]
        content = "\n\n".join(paragraphs)
        result = _split_chunks(content, max_size=100)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 120  # some tolerance for boundary

    def test_empty_content(self):
        result = _split_chunks("", max_size=100)
        assert result == [""]

    def test_exact_boundary(self):
        content = "A" * 4000
        result = _split_chunks(content, max_size=4000)
        assert result == [content]

    def test_no_paragraph_breaks(self):
        content = "A" * 5000
        result = _split_chunks(content, max_size=4000)
        # No paragraph breaks means it falls through to single chunk
        assert len(result) == 1
        assert result[0] == content


class TestToOrQuery:
    def test_single_word_unchanged(self):
        assert _to_or_query("payment") == "payment"

    def test_multi_word_or_joined(self):
        assert _to_or_query("payment docker") == "payment or docker"

    def test_three_words(self):
        assert _to_or_query("a b c") == "a or b or c"

    def test_empty_string(self):
        assert _to_or_query("") == ""

    def test_whitespace_only(self):
        assert _to_or_query("   ") == "   "


class TestRowCount:
    def test_delete_status(self):
        assert _row_count("DELETE 5") == 5

    def test_update_status(self):
        assert _row_count("UPDATE 0") == 0

    def test_insert_status(self):
        assert _row_count("INSERT 0 3") == 3

    def test_empty_string(self):
        assert _row_count("") == 0

    def test_unexpected_format(self):
        assert _row_count("UNEXPECTED") == 0


# ---------------------------------------------------------------------------
# Fixtures for MCP tool/resource tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def writable_ctx(tmp_path, monkeypatch):
    """Writable SQLite backend + patched _get_ctx for server tool tests."""
    config = GnosisMcpConfig(
        database_url=str(tmp_path / "server_test.db"),
        backend="sqlite",
        writable=True,
    )
    backend = SqliteBackend(config)
    await backend.startup()
    await backend.init_schema()
    ctx = AppContext(backend=backend, config=config)

    async def _mock_get_ctx():
        return ctx

    monkeypatch.setattr(server_mod, "_get_ctx", _mock_get_ctx)
    yield ctx
    await backend.shutdown()


@pytest.fixture
async def readonly_ctx(tmp_path, monkeypatch):
    """Read-only SQLite backend + patched _get_ctx for write-gate tests."""
    config = GnosisMcpConfig(
        database_url=str(tmp_path / "server_test.db"),
        backend="sqlite",
        writable=False,
    )
    backend = SqliteBackend(config)
    await backend.startup()
    await backend.init_schema()
    ctx = AppContext(backend=backend, config=config)

    async def _mock_get_ctx():
        return ctx

    monkeypatch.setattr(server_mod, "_get_ctx", _mock_get_ctx)
    yield ctx
    await backend.shutdown()


# ---------------------------------------------------------------------------
# MCP Tool tests — search_docs
# ---------------------------------------------------------------------------


class TestSearchDocsTool:
    @pytest.mark.asyncio
    async def test_no_results(self, writable_ctx):
        result = await search_docs("nonexistent query xyz")
        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_with_results(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "test.md",
            ["Gnosis documentation server for searching knowledge bases"],
            title="Test",
            category="guides",
        )
        result = await search_docs("gnosis documentation")
        data = json.loads(result)
        assert len(data) >= 1
        assert data[0]["file_path"] == "test.md"
        assert "score" in data[0]
        assert "content_preview" in data[0]

    @pytest.mark.asyncio
    async def test_limit_respected(self, writable_ctx):
        for i in range(6):
            await writable_ctx.backend.upsert_doc(
                f"doc{i}.md",
                [f"Content about testing topic number {i}"],
                title=f"Doc {i}",
                category="test",
            )
        result = await search_docs("testing", limit=3)
        data = json.loads(result)
        assert len(data) <= 3


# ---------------------------------------------------------------------------
# MCP Tool tests — get_doc
# ---------------------------------------------------------------------------


class TestGetDocTool:
    @pytest.mark.asyncio
    async def test_not_found(self, writable_ctx):
        result = await get_doc("nonexistent.md")
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_content(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "hello.md", ["Hello world content"], title="Hello", category="test"
        )
        result = await get_doc("hello.md")
        data = json.loads(result)
        assert data["title"] == "Hello"
        assert "Hello world content" in data["content"]

    @pytest.mark.asyncio
    async def test_max_length_truncates(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "long.md", ["A" * 500], title="Long", category="test"
        )
        result = await get_doc("long.md", max_length=50)
        data = json.loads(result)
        assert data["truncated"] is True
        assert len(data["content"]) <= 60  # 50 + "..."


# ---------------------------------------------------------------------------
# MCP Tool tests — get_related
# ---------------------------------------------------------------------------


class TestGetRelatedTool:
    @pytest.mark.asyncio
    async def test_no_links(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "solo.md", ["Solo document"], title="Solo", category="test"
        )
        result = await get_related("solo.md")
        data = json.loads(result)
        assert isinstance(data, list)
        assert data == []


# ---------------------------------------------------------------------------
# MCP Tool tests — write gate
# ---------------------------------------------------------------------------


class TestWriteGate:
    @pytest.mark.asyncio
    async def test_upsert_blocked(self, readonly_ctx):
        result = await upsert_doc("test.md", "content")
        data = json.loads(result)
        assert "error" in data
        assert "GNOSIS_MCP_WRITABLE" in data["error"]

    @pytest.mark.asyncio
    async def test_delete_blocked(self, readonly_ctx):
        result = await delete_doc("test.md")
        data = json.loads(result)
        assert "error" in data
        assert "GNOSIS_MCP_WRITABLE" in data["error"]

    @pytest.mark.asyncio
    async def test_update_metadata_blocked(self, readonly_ctx):
        result = await update_metadata("test.md", title="New")
        data = json.loads(result)
        assert "error" in data
        assert "GNOSIS_MCP_WRITABLE" in data["error"]


# ---------------------------------------------------------------------------
# MCP Tool tests — upsert_doc
# ---------------------------------------------------------------------------


class TestUpsertDocTool:
    @pytest.mark.asyncio
    async def test_upsert_creates_doc(self, writable_ctx):
        result = await upsert_doc("new.md", "# Title\n\nContent here")
        data = json.loads(result)
        assert data["action"] == "upserted"
        assert data["path"] == "new.md"
        assert data["chunks"] >= 1

    @pytest.mark.asyncio
    async def test_auto_extracts_title(self, writable_ctx):
        await upsert_doc("titled.md", "# My Title\n\nBody text")
        result = await get_doc("titled.md")
        data = json.loads(result)
        assert data["title"] == "My Title"

    @pytest.mark.asyncio
    async def test_embeddings_count_mismatch(self, writable_ctx):
        result = await upsert_doc(
            "bad.md",
            "Short content",
            embeddings=[[0.1, 0.2], [0.3, 0.4]],  # 2 embeddings for 1 chunk
        )
        data = json.loads(result)
        assert "error" in data
        assert "Embeddings count" in data["error"]


# ---------------------------------------------------------------------------
# MCP Tool tests — delete_doc
# ---------------------------------------------------------------------------


class TestDeleteDocTool:
    @pytest.mark.asyncio
    async def test_delete_existing(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "to_delete.md", ["Content"], title="Del", category="test"
        )
        result = await delete_doc("to_delete.md")
        data = json.loads(result)
        assert data["action"] == "deleted"
        assert data["chunks_deleted"] >= 1

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, writable_ctx):
        result = await delete_doc("nope.md")
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# MCP Tool tests — update_metadata
# ---------------------------------------------------------------------------


class TestUpdateMetadataTool:
    @pytest.mark.asyncio
    async def test_update_title(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "meta.md", ["Content"], title="Old", category="test"
        )
        result = await update_metadata("meta.md", title="New Title")
        data = json.loads(result)
        assert data["action"] == "metadata_updated"
        assert data["chunks_updated"] >= 1

    @pytest.mark.asyncio
    async def test_no_fields_error(self, writable_ctx):
        result = await update_metadata("meta.md")
        data = json.loads(result)
        assert "error" in data
        assert "No fields to update" in data["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, writable_ctx):
        result = await update_metadata("missing.md", title="X")
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


class TestListDocsResource:
    @pytest.mark.asyncio
    async def test_empty(self, writable_ctx):
        result = await list_docs()
        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_with_doc(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "res.md", ["Resource content"], title="Res", category="test"
        )
        result = await list_docs()
        data = json.loads(result)
        assert len(data) >= 1


class TestReadDocResource:
    @pytest.mark.asyncio
    async def test_not_found(self, writable_ctx):
        result = await read_doc_resource("nope.md")
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_content(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "readable.md", ["Readable content"], title="R", category="test"
        )
        result = await read_doc_resource("readable.md")
        assert "Readable content" in result


class TestListCategoriesResource:
    @pytest.mark.asyncio
    async def test_empty(self, writable_ctx):
        result = await list_categories()
        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_with_categories(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "a.md", ["Alpha"], title="A", category="guides"
        )
        await writable_ctx.backend.upsert_doc(
            "b.md", ["Beta"], title="B", category="reference"
        )
        result = await list_categories()
        data = json.loads(result)
        categories = {r["category"] for r in data}
        assert "guides" in categories
        assert "reference" in categories


# ---------------------------------------------------------------------------
# Webhook notification
# ---------------------------------------------------------------------------


class TestNotifyWebhook:
    @pytest.mark.asyncio
    async def test_no_url_is_noop(self):
        config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)
        # Should not raise
        await _notify_webhook(ctx, "upsert", "test.md")

    @pytest.mark.asyncio
    async def test_posts_payload(self, monkeypatch):
        config = GnosisMcpConfig(
            database_url=":memory:",
            backend="sqlite",
            webhook_url="http://localhost:9999/hook",
        )
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)

        captured = {}

        def mock_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = json.loads(req.data)

            class Resp:
                def read(self): return b""
                def __enter__(self): return self
                def __exit__(self, *a): pass

            return Resp()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
        await _notify_webhook(ctx, "upsert", "doc.md")

        assert captured["url"] == "http://localhost:9999/hook"
        assert captured["data"]["action"] == "upsert"
        assert captured["data"]["path"] == "doc.md"
        assert "timestamp" in captured["data"]

    @pytest.mark.asyncio
    async def test_error_swallowed(self, monkeypatch):
        config = GnosisMcpConfig(
            database_url=":memory:",
            backend="sqlite",
            webhook_url="http://localhost:9999/hook",
        )
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)

        def mock_urlopen(req, timeout=None):
            raise ConnectionError("refused")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
        # Should not raise
        await _notify_webhook(ctx, "delete", "doc.md")
