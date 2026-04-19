"""Tests for server helpers, MCP tools, resources, and webhook."""

import json
import urllib.request

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.db import AppContext
from gnosis_mcp.pg_backend import _row_count, _to_or_query
import gnosis_mcp.server as server_mod
from gnosis_mcp.server import (
    _apply_mmr,
    _collapse_by_doc,
    _notify_webhook,
    _split_chunks,
    delete_doc,
    get_context,
    get_doc,
    get_graph_stats,
    get_related,
    list_categories,
    list_docs,
    read_doc_resource,
    search_docs,
    search_git_history,
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


class TestApplyMmr:
    """Pure-logic tests for the MMR helper — no DB, no embedder, controlled vectors."""

    def _build(self, n: int, aligned_axis: int = 0):
        """Make n unit vectors that point mostly along `aligned_axis`."""
        import numpy as np

        vecs = []
        for i in range(n):
            v = np.zeros(4, dtype=np.float32)
            v[aligned_axis] = 1.0
            # Jitter on a distinct axis per doc so they're not identical
            v[i % 4 + 1 if i % 4 + 1 < 4 else 0] = 0.1
            v = v / np.linalg.norm(v)
            vecs.append(v.tolist())
        return vecs

    def test_lambda_one_is_identity(self):
        """λ=1.0 → pure relevance → MMR returns the input order unchanged."""
        results = [{"id": 0, "content": "a"}, {"id": 1, "content": "b"}]
        q = [1.0, 0, 0, 0]
        docs = [[1.0, 0, 0, 0], [0.9, 0.1, 0, 0]]
        assert _apply_mmr(results, q, docs, 1.0) == results

    def test_lambda_zero_is_identity_also(self):
        """Our guard returns input when λ is at either extreme — documented behaviour."""
        results = [{"id": 0}, {"id": 1}]
        q = [1.0, 0, 0, 0]
        docs = [[1.0, 0, 0, 0], [0.5, 0.5, 0, 0]]
        assert _apply_mmr(results, q, docs, 0.0) == results

    def test_empty_and_singleton_passthrough(self):
        assert _apply_mmr([], [1.0, 0], [], 0.5) == []
        assert _apply_mmr([{"id": 0}], [1.0, 0], [[1.0, 0]], 0.5) == [{"id": 0}]

    def test_dimension_mismatch_passes_through(self):
        """Defensive: if doc_embeddings count != results count, MMR bails out."""
        results = [{"id": 0}, {"id": 1}, {"id": 2}]
        q = [1.0, 0]
        docs = [[1.0, 0], [0.5, 0.5]]  # 2 vecs, 3 results
        assert _apply_mmr(results, q, docs, 0.5) == results

    def test_diversity_promotes_differently_oriented_doc(self):
        """With λ=0.3 (diversity-heavy), a less-relevant but orthogonal doc
        should be picked before a near-duplicate of the top hit."""
        results = [
            {"id": 0, "content": "very-relevant"},
            {"id": 1, "content": "relevant-duplicate"},
            {"id": 2, "content": "orthogonal-but-still-relevant"},
        ]
        q = [1.0, 0, 0, 0]
        docs = [
            [1.0, 0, 0, 0],    # top relevance
            [0.99, 0.01, 0, 0],  # near-duplicate of doc 0
            [0.6, 0, 0.8, 0],    # less relevant but diverse
        ]
        import numpy as np

        docs = [(np.array(v) / np.linalg.norm(v)).tolist() for v in docs]
        ordered = _apply_mmr(results, q, docs, lambda_=0.3)
        ids = [r["id"] for r in ordered]
        assert ids[0] == 0  # first pick always max relevance
        # Orthogonal (id=2) should come before near-duplicate (id=1) with low λ
        assert ids.index(2) < ids.index(1)

    def test_zero_query_vector_passes_through(self):
        """Degenerate all-zero query vector — bail out rather than divide by zero."""
        results = [{"id": 0}, {"id": 1}]
        q = [0.0, 0.0, 0.0, 0.0]
        docs = [[1.0, 0, 0, 0], [0.0, 1.0, 0, 0]]
        assert _apply_mmr(results, q, docs, 0.5) == results


class TestCollapseByDoc:
    def test_preserves_highest_scoring_per_doc(self):
        """First occurrence (highest score in incoming order) wins per file_path."""
        rows = [
            {"file_path": "a.md", "score": 10, "content": "first-a"},
            {"file_path": "b.md", "score": 9, "content": "first-b"},
            {"file_path": "a.md", "score": 8, "content": "second-a"},
            {"file_path": "c.md", "score": 7, "content": "first-c"},
            {"file_path": "b.md", "score": 6, "content": "second-b"},
        ]
        collapsed = _collapse_by_doc(rows)
        assert [r["file_path"] for r in collapsed] == ["a.md", "b.md", "c.md"]
        assert collapsed[0]["content"] == "first-a"

    def test_stable_on_empty(self):
        assert _collapse_by_doc([]) == []

    def test_missing_file_path_is_dropped(self):
        """Rows without a file_path key are filtered — defensive, shouldn't happen in practice."""
        rows = [{"file_path": "a.md"}, {"file_path": None}, {"no_path": True}]
        assert _collapse_by_doc(rows) == [{"file_path": "a.md"}]


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
    async def test_search_stats_tracked(self, writable_ctx):
        """Search stats counters should track total/misses/mode."""
        server_mod._search_stats["total"] = 0
        server_mod._search_stats["misses"] = 0
        server_mod._search_stats["keyword"] = 0

        await search_docs("nonexistent xyz")
        assert server_mod._search_stats["total"] == 1
        assert server_mod._search_stats["misses"] == 1
        assert server_mod._search_stats["keyword"] == 1

        await writable_ctx.backend.upsert_doc(
            "stats-test.md",
            ["Content about search stats tracking"],
            title="Stats",
            category="test",
        )
        await search_docs("search stats")
        assert server_mod._search_stats["total"] == 2
        assert server_mod._search_stats["misses"] == 1  # only first was a miss

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

    @pytest.mark.asyncio
    async def test_rerank_without_extra_returns_unranked(self, writable_ctx, monkeypatch):
        """If rerank=True but [reranking] missing, search still succeeds."""
        await writable_ctx.backend.upsert_doc(
            "a.md", ["Alpha content about search"], title="A", category="g"
        )
        await writable_ctx.backend.upsert_doc(
            "b.md", ["Beta content about search"], title="B", category="g"
        )

        def _raise_import(*_a, **_kw):
            raise ImportError("reranker not installed")

        monkeypatch.setattr("gnosis_mcp.rerank.get_reranker", _raise_import, raising=False)
        result = await search_docs("search", limit=2, rerank=True)
        data = json.loads(result)
        # Results come back regardless; no crash.
        assert isinstance(data, list)


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
# MCP Tool tests — get_context
# ---------------------------------------------------------------------------


class TestGetContextTool:
    @pytest.mark.asyncio
    async def test_empty_no_access(self, writable_ctx):
        result = await get_context()
        data = json.loads(result)
        assert data["docs"] == []
        assert "stats" in data
        assert "total_docs" in data["stats"]

    @pytest.mark.asyncio
    async def test_with_topic(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "test.md",
            ["Getting started with gnosis documentation system"],
            title="Getting Started",
            category="guides",
        )
        result = await get_context(topic="gnosis documentation")
        data = json.loads(result)
        assert len(data["docs"]) >= 1
        assert "summary" in data["docs"][0]
        assert "file_path" in data["docs"][0]

    @pytest.mark.asyncio
    async def test_without_topic_uses_access_log(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "popular.md",
            ["Popular document content about billing"],
            title="Popular",
            category="guides",
        )
        await writable_ctx.backend.log_access("popular.md", tool="get_doc")
        await writable_ctx.backend.log_access("popular.md", tool="get_doc")
        result = await get_context()
        data = json.loads(result)
        assert len(data["docs"]) >= 1
        assert data["docs"][0]["file_path"] == "popular.md"
        assert data["docs"][0]["access_count"] >= 2

    @pytest.mark.asyncio
    async def test_stats_included(self, writable_ctx):
        result = await get_context()
        data = json.loads(result)
        assert "stats" in data
        assert "total_docs" in data["stats"]
        assert "total_chunks" in data["stats"]
        assert "categories" in data["stats"]


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
        await writable_ctx.backend.upsert_doc("meta.md", ["Content"], title="Old", category="test")
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
        await writable_ctx.backend.upsert_doc("a.md", ["Alpha"], title="A", category="guides")
        await writable_ctx.backend.upsert_doc("b.md", ["Beta"], title="B", category="reference")
        result = await list_categories()
        data = json.loads(result)
        categories = {r["category"] for r in data}
        assert "guides" in categories
        assert "reference" in categories


# ---------------------------------------------------------------------------
# MCP Tool tests — search_git_history
# ---------------------------------------------------------------------------


class TestSearchGitHistoryTool:
    @pytest.mark.asyncio
    async def test_empty_query_error(self, writable_ctx):
        result = await search_git_history("")
        data = json.loads(result)
        assert "error" in data
        assert "Empty query" in data["error"]

    @pytest.mark.asyncio
    async def test_no_results(self, writable_ctx):
        result = await search_git_history("nonexistent commit xyz")
        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_searches_git_history_category(self, writable_ctx):
        # Insert a doc in git-history category
        await writable_ctx.backend.upsert_doc(
            "git-history/src/main.py",
            ["## 2026-02-20\n\nAuthor: Alice <alice@test.com>\n\nRefactored main module"],
            title="Git history for src/main.py",
            category="git-history",
        )
        # Insert a doc in a different category — should NOT appear
        await writable_ctx.backend.upsert_doc(
            "guides/main.md",
            ["Refactored main module guide"],
            title="Main guide",
            category="guides",
        )
        result = await search_git_history("refactored main")
        data = json.loads(result)
        assert len(data) >= 1
        assert all("git-history" in d["file_path"] for d in data)

    @pytest.mark.asyncio
    async def test_author_filter(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "git-history/a.py",
            ["## 2026-02-20\n\nAuthor: Alice <alice@test.com>\n\nFixed bug in a.py"],
            title="Git history for a.py",
            category="git-history",
        )
        await writable_ctx.backend.upsert_doc(
            "git-history/b.py",
            ["## 2026-02-20\n\nAuthor: Bob <bob@test.com>\n\nFixed bug in b.py"],
            title="Git history for b.py",
            category="git-history",
        )
        result = await search_git_history("fixed bug", author="Alice")
        data = json.loads(result)
        # Only Alice's result should appear
        for item in data:
            assert item["file_path"] == "git-history/a.py"

    @pytest.mark.asyncio
    async def test_file_path_filter(self, writable_ctx):
        await writable_ctx.backend.upsert_doc(
            "git-history/src/app.py",
            ["## 2026-02-20\n\nAdded feature to app"],
            title="Git history for src/app.py",
            category="git-history",
        )
        await writable_ctx.backend.upsert_doc(
            "git-history/src/util.py",
            ["## 2026-02-20\n\nAdded feature to util"],
            title="Git history for src/util.py",
            category="git-history",
        )
        result = await search_git_history("added feature", file_path="app.py")
        data = json.loads(result)
        for item in data:
            assert "app.py" in item["file_path"]


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
            webhook_allow_private=True,
        )
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)

        captured = {}

        def mock_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = json.loads(req.data)

            class Resp:
                def read(self):
                    return b""

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

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
            webhook_allow_private=True,
        )
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)

        def mock_urlopen(req, timeout=None):
            raise ConnectionError("refused")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
        # Should not raise
        await _notify_webhook(ctx, "delete", "doc.md")

    @pytest.mark.asyncio
    async def test_refuses_private_address_by_default(self, monkeypatch):
        config = GnosisMcpConfig(
            database_url=":memory:",
            backend="sqlite",
            webhook_url="http://127.0.0.1:9999/hook",
        )
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)

        called = {"n": 0}

        def mock_urlopen(req, timeout=None):
            called["n"] += 1

            class Resp:
                def read(self):
                    return b""

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

            return Resp()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
        await _notify_webhook(ctx, "upsert", "doc.md")
        assert called["n"] == 0, "Expected webhook POST to be refused for private address"


# ---------------------------------------------------------------------------
# MCP Tool tests — get_graph_stats
# ---------------------------------------------------------------------------


class TestGetGraphStatsTool:
    @pytest.mark.asyncio
    async def test_empty_graph_stats(self, writable_ctx):
        result = await get_graph_stats()
        data = json.loads(result)
        assert data["total_docs"] == 0
        assert data["total_edges"] == 0
        assert data["orphans"] == []
        assert data["hubs"] == []

    @pytest.mark.asyncio
    async def test_graph_stats_with_data(self, writable_ctx):
        await writable_ctx.backend.upsert_doc("a.md", ["A"], title="A", category="test")
        await writable_ctx.backend.upsert_doc("b.md", ["B"], title="B", category="test")
        await writable_ctx.backend.insert_links("a.md", ["b.md"])
        result = await get_graph_stats()
        data = json.loads(result)
        assert data["total_edges"] == 1
        assert len(data["hubs"]) > 0
