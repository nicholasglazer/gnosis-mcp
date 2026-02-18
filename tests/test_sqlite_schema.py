"""Tests for SQLite schema DDL."""

from gnosis_mcp.sqlite_schema import get_sqlite_schema


class TestGetSqliteSchema:
    def test_returns_list_of_statements(self):
        stmts = get_sqlite_schema()
        assert isinstance(stmts, list)
        assert len(stmts) > 0

    def test_creates_chunks_table(self):
        stmts = get_sqlite_schema()
        ddl = "\n".join(stmts)
        assert "CREATE TABLE IF NOT EXISTS documentation_chunks" in ddl
        assert "file_path TEXT NOT NULL" in ddl
        assert "content TEXT NOT NULL" in ddl
        assert "chunk_index INTEGER" in ddl
        assert "content_hash TEXT" in ddl
        assert "UNIQUE (file_path, chunk_index)" in ddl

    def test_creates_fts5_table(self):
        stmts = get_sqlite_schema()
        ddl = "\n".join(stmts)
        assert "CREATE VIRTUAL TABLE IF NOT EXISTS documentation_chunks_fts USING fts5" in ddl
        assert "tokenize='porter'" in ddl

    def test_creates_sync_triggers(self):
        stmts = get_sqlite_schema()
        ddl = "\n".join(stmts)
        assert "chunks_ai AFTER INSERT" in ddl
        assert "chunks_ad AFTER DELETE" in ddl
        assert "chunks_au AFTER UPDATE" in ddl

    def test_creates_links_table(self):
        stmts = get_sqlite_schema()
        ddl = "\n".join(stmts)
        assert "CREATE TABLE IF NOT EXISTS documentation_links" in ddl
        assert "source_path TEXT NOT NULL" in ddl
        assert "target_path TEXT NOT NULL" in ddl

    def test_creates_indexes(self):
        stmts = get_sqlite_schema()
        ddl = "\n".join(stmts)
        assert "idx_chunks_file_path" in ddl
        assert "idx_chunks_category" in ddl
        assert "idx_links_source" in ddl
        assert "idx_links_target" in ddl
