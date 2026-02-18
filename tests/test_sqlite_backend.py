"""Tests for SqliteBackend — full lifecycle with in-memory database."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.sqlite_backend import SqliteBackend, _to_fts5_query


def _make_backend() -> SqliteBackend:
    """Create a SqliteBackend with in-memory database."""
    config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
    return SqliteBackend(config)


class TestFts5Query:
    def test_simple_words(self):
        assert _to_fts5_query("billing guide") == '"billing" "guide"'

    def test_strips_special_chars(self):
        assert _to_fts5_query('test*') == '"test"'
        assert _to_fts5_query('"quoted"') == '"quoted"'
        assert _to_fts5_query("a-b") == '"ab"'

    def test_empty_string(self):
        assert _to_fts5_query("") == '""'

    def test_single_word(self):
        assert _to_fts5_query("search") == '"search"'


class TestSqliteBackendLifecycle:
    @pytest.fixture
    async def backend(self):
        b = _make_backend()
        await b.startup()
        await b.init_schema()
        yield b
        await b.shutdown()

    async def test_startup_shutdown(self):
        b = _make_backend()
        await b.startup()
        assert b._db is not None
        await b.shutdown()
        assert b._db is None

    async def test_init_schema(self, backend):
        health = await backend.check_health()
        assert health["backend"] == "sqlite"
        assert health["chunks_table_exists"] is True
        assert health["fts_table_exists"] is True
        assert health["links_table_exists"] is True

    async def test_upsert_and_get_doc(self, backend):
        count = await backend.upsert_doc(
            "guides/test.md",
            ["# Test\n\nFirst chunk", "## Section\n\nSecond chunk"],
            title="Test Doc",
            category="guides",
        )
        assert count == 2

        chunks = await backend.get_doc("guides/test.md")
        assert len(chunks) == 2
        assert chunks[0]["title"] == "Test Doc"
        assert chunks[0]["content"] == "# Test\n\nFirst chunk"
        assert chunks[1]["content"] == "## Section\n\nSecond chunk"
        assert chunks[0]["category"] == "guides"

    async def test_search(self, backend):
        await backend.upsert_doc(
            "guides/billing.md",
            ["Billing guide for Stripe integration and payment processing"],
            title="Billing Guide",
            category="guides",
        )
        await backend.upsert_doc(
            "guides/auth.md",
            ["Authentication guide for Supabase auth and JWT tokens"],
            title="Auth Guide",
            category="guides",
        )

        results = await backend.search("billing payment")
        assert len(results) >= 1
        assert results[0]["file_path"] == "guides/billing.md"
        assert results[0]["score"] > 0

    async def test_search_with_category(self, backend):
        await backend.upsert_doc(
            "guides/a.md", ["Content about testing"], title="A", category="guides"
        )
        await backend.upsert_doc(
            "ops/b.md", ["Content about testing"], title="B", category="ops"
        )

        results = await backend.search("testing", category="ops")
        assert all(r["category"] == "ops" for r in results)

    async def test_delete_doc(self, backend):
        await backend.upsert_doc(
            "guides/del.md", ["Delete me"], title="Delete", category="guides"
        )
        result = await backend.delete_doc("guides/del.md")
        assert result["chunks_deleted"] == 1

        chunks = await backend.get_doc("guides/del.md")
        assert len(chunks) == 0

    async def test_delete_nonexistent(self, backend):
        result = await backend.delete_doc("nonexistent.md")
        assert result["chunks_deleted"] == 0

    async def test_update_metadata(self, backend):
        await backend.upsert_doc(
            "guides/meta.md", ["Content"], title="Old", category="old"
        )
        affected = await backend.update_metadata(
            "guides/meta.md", title="New Title", category="new"
        )
        assert affected == 1

        chunks = await backend.get_doc("guides/meta.md")
        assert chunks[0]["title"] == "New Title"
        assert chunks[0]["category"] == "new"

    async def test_list_docs(self, backend):
        await backend.upsert_doc("a.md", ["A1", "A2"], title="A", category="cat1")
        await backend.upsert_doc("b.md", ["B1"], title="B", category="cat2")

        docs = await backend.list_docs()
        assert len(docs) == 2
        a_doc = next(d for d in docs if d["file_path"] == "a.md")
        assert a_doc["chunks"] == 2

    async def test_list_categories(self, backend):
        await backend.upsert_doc("a.md", ["A"], title="A", category="guides")
        await backend.upsert_doc("b.md", ["B"], title="B", category="guides")
        await backend.upsert_doc("c.md", ["C"], title="C", category="ops")

        cats = await backend.list_categories()
        assert len(cats) == 2
        guides = next(c for c in cats if c["category"] == "guides")
        assert guides["docs"] == 2

    async def test_stats(self, backend):
        await backend.upsert_doc("a.md", ["Hello world"], title="A", category="test")
        s = await backend.stats()
        assert s["docs"] == 1
        assert s["chunks"] == 1
        assert s["content_bytes"] > 0

    async def test_export_docs(self, backend):
        await backend.upsert_doc(
            "a.md", ["Chunk 1", "Chunk 2"], title="A", category="guides"
        )
        docs = await backend.export_docs()
        assert len(docs) == 1
        assert "Chunk 1" in docs[0]["content"]
        assert "Chunk 2" in docs[0]["content"]

    async def test_export_with_category_filter(self, backend):
        await backend.upsert_doc("a.md", ["A"], title="A", category="guides")
        await backend.upsert_doc("b.md", ["B"], title="B", category="ops")

        docs = await backend.export_docs(category="ops")
        assert len(docs) == 1
        assert docs[0]["file_path"] == "b.md"

    async def test_get_related_no_links(self, backend):
        result = await backend.get_related("any.md")
        assert result is not None  # Table exists but is empty
        assert result == []

    async def test_ingest_file(self, backend):
        chunks = [
            {"title": "Intro", "content": "Introduction content"},
            {"title": "Details", "content": "Detail content"},
        ]
        count = await backend.ingest_file(
            "doc.md",
            chunks,
            title="Doc",
            category="guides",
            audience="all",
            has_tags_col=True,
            has_hash_col=True,
            content_hash="abc123",
        )
        assert count == 2

        rows = await backend.get_doc("doc.md")
        assert len(rows) == 2

    async def test_has_column(self, backend):
        assert await backend.has_column("documentation_chunks", "content") is True
        assert await backend.has_column("documentation_chunks", "nonexistent") is False

    async def test_pending_embeddings(self, backend):
        await backend.upsert_doc("a.md", ["Content"], title="A", category="test")

        count = await backend.count_pending_embeddings()
        assert count == 1

        pending = await backend.get_pending_embeddings(10)
        assert len(pending) == 1
        assert pending[0]["content"] == "Content"

    async def test_upsert_replaces_existing(self, backend):
        await backend.upsert_doc("a.md", ["V1"], title="V1", category="test")
        await backend.upsert_doc("a.md", ["V2a", "V2b"], title="V2", category="test")

        chunks = await backend.get_doc("a.md")
        assert len(chunks) == 2
        assert chunks[0]["title"] == "V2"
