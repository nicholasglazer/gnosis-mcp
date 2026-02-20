"""Tests for schema SQL generation."""

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.schema import get_init_sql


class TestGetInitSql:
    def test_default_schema(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "CREATE SCHEMA IF NOT EXISTS public;" in sql
        assert "public.documentation_chunks" in sql
        assert "public.documentation_links" in sql
        assert "vector(1536)" in sql

    def test_custom_schema_and_tables(self):
        cfg = GnosisMcpConfig(
            database_url="postgresql://localhost/db",
            schema="docs",
            chunks_table="pages",
            links_table="refs",
        )
        sql = get_init_sql(cfg)
        assert "CREATE SCHEMA IF NOT EXISTS docs;" in sql
        assert "docs.pages" in sql
        assert "docs.refs" in sql
        assert "search_pages(" in sql

    def test_custom_embedding_dim(self):
        cfg = GnosisMcpConfig(
            database_url="postgresql://localhost/db",
            embedding_dim=768,
        )
        sql = get_init_sql(cfg)
        assert "vector(768)" in sql
        assert "vector(1536)" not in sql

    def test_content_hash_column(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "content_hash text" in sql

    def test_idempotent_statements(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "IF NOT EXISTS" in sql
        assert "CREATE OR REPLACE FUNCTION" in sql

    def test_creates_indexes(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "idx_documentation_chunks_file_path" in sql
        assert "idx_documentation_chunks_category" in sql
        assert "idx_documentation_chunks_tsv" in sql
        assert "idx_documentation_links_source" in sql
        assert "idx_documentation_links_target" in sql

    def test_creates_hnsw_index(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "idx_documentation_chunks_embedding" in sql
        assert "USING hnsw" in sql
        assert "vector_cosine_ops" in sql
        assert "m = 16" in sql
        assert "ef_construction = 64" in sql

    def test_creates_hybrid_search_function(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "search_documentation_chunks_hybrid(" in sql
        assert "p_embedding vector(1536)" in sql
        assert "p_query_text text" in sql
        assert "p_categories text[]" in sql
        assert "p_limit integer" in sql
        assert "<=>" in sql  # cosine distance operator

    def test_hybrid_function_scoring_weights(self):
        cfg = GnosisMcpConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        # Linear blending: 0.4 keyword + 0.6 semantic (PG uses linear, SQLite uses RRF)
        assert "* 0.4" in sql
        assert "* 0.6" in sql
        # Cosine similarity threshold for semantic-only matches
        assert "< 0.8" in sql

    def test_hybrid_function_custom_dim(self):
        cfg = GnosisMcpConfig(
            database_url="postgresql://localhost/db",
            embedding_dim=384,
        )
        sql = get_init_sql(cfg)
        assert "p_embedding vector(384)" in sql
        assert "vector(384)" in sql

    def test_hybrid_function_custom_table(self):
        cfg = GnosisMcpConfig(
            database_url="postgresql://localhost/db",
            schema="internal",
            chunks_table="docs",
        )
        sql = get_init_sql(cfg)
        assert "internal.search_docs_hybrid(" in sql
        assert "FROM internal.docs c" in sql
