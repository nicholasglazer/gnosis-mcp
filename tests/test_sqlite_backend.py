"""Tests for SqliteBackend — full lifecycle with in-memory database."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.sqlite_backend import SqliteBackend, _to_fts5_query


def _make_backend() -> SqliteBackend:
    """Create a SqliteBackend with in-memory database."""
    config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
    return SqliteBackend(config)


class TestFts5Query:
    def test_multi_word_uses_or(self):
        """Multi-word queries use OR for broader matching."""
        result = _to_fts5_query("billing guide")
        assert result == '"billing" OR "guide"'
        assert "OR" in result

    def test_three_words(self):
        result = _to_fts5_query("pandas data analysis")
        assert result == '"pandas" OR "data" OR "analysis"'

    def test_strips_special_chars(self):
        assert _to_fts5_query('test*') == '"test"'
        assert _to_fts5_query('"quoted"') == '"quoted"'
        assert _to_fts5_query("a-b") == '"ab"'

    def test_empty_string(self):
        assert _to_fts5_query("") == '""'

    def test_single_word(self):
        assert _to_fts5_query("search") == '"search"'

    def test_all_special_chars(self):
        """If all chars are special, return empty quoted string."""
        assert _to_fts5_query("*+-") == '""'


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
        assert pending[0]["title"] == "A"
        assert pending[0]["file_path"] == "a.md"

    async def test_search_multi_word_or(self, backend):
        """Multi-word search uses OR — should match docs with any term."""
        await backend.upsert_doc(
            "a.md", ["Pandas is a data analysis library"], title="A", category="test"
        )
        await backend.upsert_doc(
            "b.md", ["Flask is a web framework"], title="B", category="test"
        )

        # "pandas web" — one word in each doc, OR should find both
        results = await backend.search("pandas web")
        assert len(results) == 2

    async def test_insert_links_and_get_related(self, backend):
        """insert_links + get_related returns bidirectional links."""
        await backend.upsert_doc("a.md", ["A content"], title="A", category="test")
        await backend.upsert_doc("b.md", ["B content"], title="B", category="test")
        await backend.upsert_doc("c.md", ["C content"], title="C", category="test")

        inserted = await backend.insert_links("a.md", ["b.md", "c.md"])
        assert inserted == 2

        # Outgoing from a.md
        related = await backend.get_related("a.md")
        outgoing = [r for r in related if r["direction"] == "outgoing"]
        paths = {r["related_path"] for r in outgoing}
        assert paths == {"b.md", "c.md"}

        # Incoming to b.md (should find a.md)
        related_b = await backend.get_related("b.md")
        incoming = [r for r in related_b if r["direction"] == "incoming"]
        assert any(r["related_path"] == "a.md" for r in incoming)

    async def test_search_has_highlight(self, backend):
        """Search results include a highlight field."""
        await backend.upsert_doc(
            "a.md", ["Installation guide for gnosis-mcp"], title="Install", category="test"
        )
        results = await backend.search("installation")
        assert len(results) >= 1
        assert results[0].get("highlight") is not None

    async def test_update_metadata_with_tags(self, backend):
        """Tags JSON roundtrip: update_metadata stores JSON, get_doc returns list."""
        await backend.upsert_doc("a.md", ["Content"], title="A", category="test")
        await backend.update_metadata("a.md", tags=["python", "backend"])
        chunks = await backend.get_doc("a.md")
        tags = chunks[0].get("tags")
        # Tags are stored as JSON string in SQLite, should be parsed back
        if isinstance(tags, str):
            import json
            tags = json.loads(tags)
        assert tags == ["python", "backend"]

    async def test_upsert_replaces_existing(self, backend):
        await backend.upsert_doc("a.md", ["V1"], title="V1", category="test")
        await backend.upsert_doc("a.md", ["V2a", "V2b"], title="V2", category="test")

        chunks = await backend.get_doc("a.md")
        assert len(chunks) == 2
        assert chunks[0]["title"] == "V2"

    async def test_empty_query_returns_empty(self, backend):
        """Empty or whitespace-only queries return empty list."""
        assert await backend.search("") == []
        assert await backend.search("   ") == []
        assert await backend.search("\n\t") == []

    async def test_file_path_query_fallback(self, backend):
        """Queries containing / or . fall back to file_path LIKE search."""
        await backend.ingest_file(
            "src/gnosis_mcp/server.py",
            [{"title": "Server", "content": "FastMCP server implementation"}],
            title="Server",
            category="code",
            audience="all",
            has_tags_col=True,
            has_hash_col=True,
            content_hash="abc",
        )

        # FTS5 strips slashes, but file_path LIKE fallback should find it
        results = await backend.search("gnosis_mcp/server.py")
        assert len(results) >= 1
        assert results[0]["file_path"] == "src/gnosis_mcp/server.py"

    async def test_title_boost_ranks_title_match_higher(self, backend):
        """BM25 title weight (10x) should rank title matches above content-only matches."""
        await backend.upsert_doc(
            "title-match.md",
            ["General introduction to the library"],
            title="Authentication Guide",
            category="test",
        )
        await backend.upsert_doc(
            "content-match.md",
            ["This covers authentication setup and configuration"],
            title="General Setup",
            category="test",
        )

        results = await backend.search("authentication")
        assert len(results) == 2
        # Title match should come first due to 10x title weight
        assert results[0]["file_path"] == "title-match.md"
        assert results[0]["score"] > results[1]["score"]


class TestAccessLog:
    @pytest.fixture
    async def backend(self):
        b = _make_backend()
        await b.startup()
        await b.init_schema()
        yield b
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_log_access(self, backend):
        """log_access inserts and get_top_accessed retrieves."""
        await backend.upsert_doc("a.md", ["Content A"], title="Doc A", category="guides")
        await backend.log_access("a.md", tool="get_doc")
        await backend.log_access("a.md", tool="search_docs", query="test query")
        top = await backend.get_top_accessed(limit=10, days=30)
        assert len(top) == 1
        assert top[0]["file_path"] == "a.md"
        assert top[0]["access_count"] == 2
        assert top[0]["title"] == "Doc A"
        assert top[0]["category"] == "guides"

    @pytest.mark.asyncio
    async def test_ordering(self, backend):
        """More accesses = higher rank."""
        await backend.upsert_doc("a.md", ["A"], title="A", category="test")
        await backend.upsert_doc("b.md", ["B"], title="B", category="test")
        await backend.log_access("a.md", tool="get_doc")
        for _ in range(3):
            await backend.log_access("b.md", tool="get_doc")
        top = await backend.get_top_accessed(limit=10, days=30)
        assert top[0]["file_path"] == "b.md"
        assert top[0]["access_count"] == 3
        assert top[1]["file_path"] == "a.md"
        assert top[1]["access_count"] == 1

    @pytest.mark.asyncio
    async def test_category_filter(self, backend):
        """Category filter limits results."""
        await backend.upsert_doc("a.md", ["A"], title="A", category="guides")
        await backend.upsert_doc("b.md", ["B"], title="B", category="ops")
        await backend.log_access("a.md", tool="get_doc")
        await backend.log_access("b.md", tool="get_doc")
        top = await backend.get_top_accessed(limit=10, days=30, category="ops")
        assert len(top) == 1
        assert top[0]["file_path"] == "b.md"

    @pytest.mark.asyncio
    async def test_empty(self, backend):
        """No accesses returns empty list."""
        top = await backend.get_top_accessed(limit=10, days=30)
        assert top == []

    @pytest.mark.asyncio
    async def test_purge(self, backend):
        """Purge with days=0 deletes everything."""
        await backend.log_access("a.md", tool="get_doc")
        # Backdate the row so it's older than "now"
        await backend._db.execute(
            "UPDATE search_access_log SET accessed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')"
        )
        await backend._db.commit()
        deleted = await backend.purge_access_log(days=0)
        assert deleted >= 1
        top = await backend.get_top_accessed(limit=10, days=30)
        assert top == []

    @pytest.mark.asyncio
    async def test_missing_table_no_error(self):
        """log_access doesn't raise if table is missing."""
        b = _make_backend()
        await b.startup()
        # Don't init_schema — table doesn't exist
        await b.log_access("a.md", tool="get_doc")  # Should not raise
        await b.shutdown()


class TestGetRelatedEnriched:
    @pytest.fixture
    async def backend(self):
        b = _make_backend()
        await b.startup()
        await b.init_schema()
        yield b
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_depth_1_default(self, backend):
        """Default depth=1 is backward compatible."""
        await backend.upsert_doc("a.md", ["A"], title="A")
        await backend.upsert_doc("b.md", ["B"], title="B")
        await backend.insert_links("a.md", ["b.md"])
        related = await backend.get_related("a.md")
        assert len(related) == 1
        assert related[0]["related_path"] == "b.md"
        assert related[0]["direction"] == "outgoing"

    @pytest.mark.asyncio
    async def test_depth_2(self, backend):
        """Depth=2 traverses two hops."""
        await backend.upsert_doc("a.md", ["A"], title="A")
        await backend.upsert_doc("b.md", ["B"], title="B")
        await backend.upsert_doc("c.md", ["C"], title="C")
        await backend.insert_links("a.md", ["b.md"])
        await backend.insert_links("b.md", ["c.md"])
        related = await backend.get_related("a.md", depth=2)
        paths = {r["related_path"] for r in related}
        assert "b.md" in paths
        assert "c.md" in paths
        # c.md should be at hops=2
        c_entry = [r for r in related if r["related_path"] == "c.md"][0]
        assert c_entry["hops"] == 2

    @pytest.mark.asyncio
    async def test_relation_type_filter(self, backend):
        """Filtering by relation_type excludes other types."""
        await backend.upsert_doc("a.md", ["A"], title="A")
        await backend.upsert_doc("b.md", ["B"], title="B")
        await backend.upsert_doc("c.md", ["C"], title="C")
        await backend.insert_links("a.md", ["b.md"], relation_type="relates_to")
        await backend.insert_links("a.md", ["c.md"], relation_type="git_co_change")
        filtered = await backend.get_related("a.md", relation_type="relates_to")
        paths = {r["related_path"] for r in filtered}
        assert "b.md" in paths
        assert "c.md" not in paths

    @pytest.mark.asyncio
    async def test_include_titles(self, backend):
        """include_titles returns title and category."""
        await backend.upsert_doc("a.md", ["A"], title="Doc A", category="guides")
        await backend.upsert_doc("b.md", ["B"], title="Doc B", category="arch")
        await backend.insert_links("a.md", ["b.md"])
        related = await backend.get_related("a.md", include_titles=True)
        assert len(related) == 1
        assert related[0]["title"] == "Doc B"
        assert related[0]["category"] == "arch"

    @pytest.mark.asyncio
    async def test_cycle_safe(self, backend):
        """Cycles don't cause infinite loops."""
        await backend.upsert_doc("a.md", ["A"], title="A")
        await backend.upsert_doc("b.md", ["B"], title="B")
        await backend.insert_links("a.md", ["b.md"])
        await backend.insert_links("b.md", ["a.md"])
        related = await backend.get_related("a.md", depth=3)
        paths = {r["related_path"] for r in related}
        assert paths == {"b.md"}  # No duplicates, no infinite loop


class TestGraphStats:
    @pytest.fixture
    async def backend(self):
        b = _make_backend()
        await b.startup()
        await b.init_schema()
        yield b
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_empty(self, backend):
        """Empty database returns zero stats."""
        stats = await backend.get_graph_stats()
        assert stats["total_docs"] == 0
        assert stats["total_edges"] == 0
        assert stats["orphans"] == []
        assert stats["hubs"] == []

    @pytest.mark.asyncio
    async def test_orphans(self, backend):
        """Docs with no links appear in orphans."""
        await backend.upsert_doc("lonely.md", ["Content"], title="Lonely", category="test")
        stats = await backend.get_graph_stats()
        orphan_paths = [o["path"] for o in stats["orphans"]]
        assert "lonely.md" in orphan_paths

    @pytest.mark.asyncio
    async def test_hubs(self, backend):
        """Most connected doc ranks first in hubs."""
        await backend.upsert_doc("hub.md", ["Hub"], title="Hub")
        await backend.upsert_doc("a.md", ["A"], title="A")
        await backend.upsert_doc("b.md", ["B"], title="B")
        await backend.upsert_doc("c.md", ["C"], title="C")
        await backend.insert_links("hub.md", ["a.md", "b.md", "c.md"])
        stats = await backend.get_graph_stats()
        assert stats["hubs"][0]["path"] == "hub.md"
        assert stats["hubs"][0]["connections"] >= 3

    @pytest.mark.asyncio
    async def test_relation_distribution(self, backend):
        """Relation type counts are accurate."""
        await backend.upsert_doc("a.md", ["A"], title="A")
        await backend.upsert_doc("b.md", ["B"], title="B")
        await backend.insert_links("a.md", ["b.md"], relation_type="relates_to")
        await backend.insert_links("a.md", ["b.md"], relation_type="content_link")
        stats = await backend.get_graph_stats()
        type_map = {r["type"]: r["count"] for r in stats["relation_types"]}
        assert type_map["relates_to"] == 1
        assert type_map["content_link"] == 1
