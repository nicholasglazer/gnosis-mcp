"""Tests for SQLite hybrid search (sqlite-vec integration)."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.sqlite_backend import SqliteBackend
from gnosis_mcp.sqlite_schema import get_vec0_schema


class TestVec0Schema:
    def test_default_dimension(self):
        stmts = get_vec0_schema()
        joined = "\n".join(stmts)
        assert "float[384]" in joined
        assert "documentation_chunks_vec" in joined

    def test_custom_dimension(self):
        stmts = get_vec0_schema(dim=768)
        assert any("float[768]" in s for s in stmts)

    def test_creates_virtual_table(self):
        stmts = get_vec0_schema()
        create = next(s for s in stmts if "CREATE VIRTUAL TABLE" in s)
        assert "USING vec0" in create
        assert "chunk_id INTEGER PRIMARY KEY" in create

    def test_delete_sync_trigger(self):
        """chunks_ad_vec trigger mirrors chunks_ad — keeps vec0 in lockstep."""
        stmts = get_vec0_schema()
        trigger = next((s for s in stmts if "TRIGGER" in s), None)
        assert trigger is not None, "vec0 schema must include delete-sync trigger"
        assert "chunks_ad_vec" in trigger
        assert "AFTER DELETE ON documentation_chunks" in trigger
        assert "DELETE FROM documentation_chunks_vec" in trigger


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

    async def test_vec0_no_orphans_after_upsert_delete(self, backend):
        """Regression: deleting or re-upserting a doc must not leak vec0 rows.

        Before v0.11.3 the `documentation_chunks` DELETE had no corresponding
        trigger on `documentation_chunks_vec`, so every `upsert_doc` on an
        existing path (delete-then-insert pattern) leaked the old vectors.
        This test asserts count parity: vec0 row count == chunks with
        embedding set.
        """
        if not backend._has_vec:
            pytest.skip("sqlite-vec not available in this environment")

        async def _count(sql: str) -> int:
            cur = await backend._db.execute(sql)
            row = await cur.fetchone()
            return row[0]

        await backend.upsert_doc(
            "guide.md", ["first", "second"], title="G", category="test"
        )
        # Embed both chunks so they appear in vec0
        ids = [
            r[0]
            for r in await (
                await backend._db.execute(
                    "SELECT id FROM documentation_chunks WHERE file_path='guide.md' ORDER BY chunk_index"
                )
            ).fetchall()
        ]
        for cid in ids:
            await backend.set_embedding(cid, [0.1] * 384)

        assert await _count("SELECT COUNT(*) FROM documentation_chunks_vec") == 2

        # Upsert with different content — triggers delete+reinsert of chunks
        await backend.upsert_doc(
            "guide.md", ["replacement"], title="G", category="test"
        )
        new_id_row = await (
            await backend._db.execute(
                "SELECT id FROM documentation_chunks WHERE file_path='guide.md'"
            )
        ).fetchone()
        await backend.set_embedding(new_id_row[0], [0.3] * 384)

        vec_after = await _count("SELECT COUNT(*) FROM documentation_chunks_vec")
        chunks_after = await _count(
            "SELECT COUNT(*) FROM documentation_chunks WHERE embedding IS NOT NULL"
        )
        assert vec_after == chunks_after == 1, (
            f"vec0 leaked: {vec_after} vectors vs {chunks_after} embedded chunks"
        )

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
        results = await backend.search("search", query_embedding=fake_embedding)
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
