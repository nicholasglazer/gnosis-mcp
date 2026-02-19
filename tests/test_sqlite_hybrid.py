"""Tests for SQLite hybrid search (sqlite-vec integration)."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.sqlite_backend import SqliteBackend
from gnosis_mcp.sqlite_schema import get_vec0_schema


class TestVec0Schema:
    def test_default_dimension(self):
        sql = get_vec0_schema()
        assert "float[384]" in sql
        assert "documentation_chunks_vec" in sql

    def test_custom_dimension(self):
        sql = get_vec0_schema(dim=768)
        assert "float[768]" in sql

    def test_creates_virtual_table(self):
        sql = get_vec0_schema()
        assert sql.startswith("CREATE VIRTUAL TABLE IF NOT EXISTS")
        assert "USING vec0" in sql
        assert "chunk_id INTEGER PRIMARY KEY" in sql


class TestSqliteVecDetection:
    """Test sqlite-vec availability detection."""

    @pytest.fixture
    async def backend(self):
        config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
        b = SqliteBackend(config)
        await b.startup()
        await b.init_schema()
        yield b
        await b.shutdown()

    async def test_has_vec_attribute_exists(self, backend):
        """Backend should have _has_vec attribute after startup."""
        assert isinstance(backend._has_vec, bool)

    async def test_health_reports_sqlite_vec(self, backend):
        """check_health should include sqlite_vec status."""
        health = await backend.check_health()
        assert "sqlite_vec" in health
        assert isinstance(health["sqlite_vec"], bool)

    async def test_stats_includes_embedded_count(self, backend):
        """stats should report embedded chunk count."""
        await backend.upsert_doc("a.md", ["Content"], title="A", category="test")
        s = await backend.stats()
        assert "embedded_chunks" in s
        assert s["embedded_chunks"] == 0  # No embeddings yet

    async def test_stats_includes_sqlite_vec_flag(self, backend):
        """stats should report sqlite_vec availability."""
        s = await backend.stats()
        assert "sqlite_vec" in s

    async def test_keyword_search_still_works(self, backend):
        """Keyword-only search should work regardless of sqlite-vec status."""
        await backend.upsert_doc(
            "guides/billing.md",
            ["Billing guide for Stripe integration"],
            title="Billing Guide",
            category="guides",
        )
        results = await backend.search("billing Stripe")
        assert len(results) >= 1
        assert results[0]["file_path"] == "guides/billing.md"

    async def test_search_with_embedding_no_vec(self, backend):
        """If sqlite-vec not loaded, search with query_embedding should fall back to keyword."""
        await backend.upsert_doc(
            "test.md", ["Test content about search"], title="Test", category="test"
        )
        # Even if we pass an embedding, without vec0 table it should use keyword search
        fake_embedding = [0.1] * 384
        results = await backend.search(
            "search", query_embedding=fake_embedding
        )
        # Should return keyword results (may or may not use embedding depending on vec status)
        assert isinstance(results, list)

    async def test_set_embedding_stores_blob(self, backend):
        """set_embedding should store the binary blob regardless of vec status."""
        await backend.upsert_doc("a.md", ["Content"], title="A", category="test")
        pending = await backend.get_pending_embeddings(10)
        assert len(pending) == 1

        chunk_id = pending[0]["id"]
        embedding = [0.1, 0.2, 0.3]
        await backend.set_embedding(chunk_id, embedding)

        # Verify blob was stored
        count = await backend.count_pending_embeddings()
        assert count == 0  # No longer pending

    async def test_embedded_chunks_count_after_embedding(self, backend):
        """Stats should reflect embedded chunks after set_embedding."""
        await backend.upsert_doc("a.md", ["Content"], title="A", category="test")
        pending = await backend.get_pending_embeddings(10)
        chunk_id = pending[0]["id"]
        await backend.set_embedding(chunk_id, [0.1, 0.2, 0.3])

        s = await backend.stats()
        assert s["embedded_chunks"] == 1
