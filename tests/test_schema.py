"""Tests for schema SQL generation."""

from ansuz.config import AnsuzConfig
from ansuz.schema import get_init_sql


class TestGetInitSql:
    def test_default_schema(self):
        cfg = AnsuzConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "CREATE SCHEMA IF NOT EXISTS public;" in sql
        assert "public.documentation_chunks" in sql
        assert "public.documentation_links" in sql
        assert "vector(1536)" in sql

    def test_custom_schema_and_tables(self):
        cfg = AnsuzConfig(
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
        cfg = AnsuzConfig(
            database_url="postgresql://localhost/db",
            embedding_dim=768,
        )
        sql = get_init_sql(cfg)
        assert "vector(768)" in sql
        assert "vector(1536)" not in sql

    def test_idempotent_statements(self):
        cfg = AnsuzConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "IF NOT EXISTS" in sql
        assert "CREATE OR REPLACE FUNCTION" in sql

    def test_creates_indexes(self):
        cfg = AnsuzConfig(database_url="postgresql://localhost/db")
        sql = get_init_sql(cfg)
        assert "idx_documentation_chunks_file_path" in sql
        assert "idx_documentation_chunks_category" in sql
        assert "idx_documentation_chunks_tsv" in sql
        assert "idx_documentation_links_source" in sql
        assert "idx_documentation_links_target" in sql
