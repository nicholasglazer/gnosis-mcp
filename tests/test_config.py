"""Tests for SteleConfig."""

import pytest

from stele.config import SteleConfig, _validate_identifier


class TestFromEnv:
    def test_requires_database_url(self, monkeypatch):
        monkeypatch.delenv("STELE_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValueError, match="DATABASE_URL"):
            SteleConfig.from_env()

    def test_stele_database_url(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/docs")
        cfg = SteleConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/docs"

    def test_fallback_to_database_url(self, monkeypatch):
        monkeypatch.delenv("STELE_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/fallback")
        cfg = SteleConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/fallback"

    def test_stele_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/stele")
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/other")
        cfg = SteleConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/stele"


class TestDefaults:
    def test_default_schema(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        cfg = SteleConfig.from_env()
        assert cfg.schema == "public"
        assert cfg.chunks_table == "documentation_chunks"
        assert cfg.links_table == "documentation_links"
        assert cfg.search_function is None
        assert cfg.embedding_dim == 1536

    def test_qualified_table_names(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_SCHEMA", "internal")
        cfg = SteleConfig.from_env()
        assert cfg.qualified_chunks_table == "internal.documentation_chunks"
        assert cfg.qualified_links_table == "internal.documentation_links"


class TestCustomConfig:
    def test_custom_schema_and_tables(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_SCHEMA", "docs")
        monkeypatch.setenv("STELE_CHUNKS_TABLE", "pages")
        monkeypatch.setenv("STELE_LINKS_TABLE", "refs")
        cfg = SteleConfig.from_env()
        assert cfg.schema == "docs"
        assert cfg.chunks_table == "pages"
        assert cfg.links_table == "refs"
        assert cfg.qualified_chunks_table == "docs.pages"

    def test_custom_search_function(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_SEARCH_FUNCTION", "internal.search_docs")
        cfg = SteleConfig.from_env()
        assert cfg.search_function == "internal.search_docs"

    def test_custom_column_names(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_COL_FILE_PATH", "path")
        monkeypatch.setenv("STELE_COL_CONTENT", "body")
        cfg = SteleConfig.from_env()
        assert cfg.col_file_path == "path"
        assert cfg.col_content == "body"

    def test_pool_settings(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_POOL_MIN", "2")
        monkeypatch.setenv("STELE_POOL_MAX", "10")
        cfg = SteleConfig.from_env()
        assert cfg.pool_min == 2
        assert cfg.pool_max == 10

    def test_embedding_dim(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_EMBEDDING_DIM", "768")
        cfg = SteleConfig.from_env()
        assert cfg.embedding_dim == 768

    def test_invalid_int_env_var(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_POOL_MAX", "abc")
        with pytest.raises(ValueError, match="STELE_POOL_MAX must be an integer"):
            SteleConfig.from_env()


class TestMultiTable:
    def test_single_table(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        cfg = SteleConfig.from_env()
        assert cfg.chunks_tables == ["documentation_chunks"]
        assert not cfg.multi_table
        assert cfg.qualified_chunks_table == "public.documentation_chunks"

    def test_comma_separated_tables(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_CHUNKS_TABLE", "docs_v1,docs_v2,api_docs")
        cfg = SteleConfig.from_env()
        assert cfg.chunks_tables == ["docs_v1", "docs_v2", "api_docs"]
        assert cfg.multi_table
        assert cfg.qualified_chunks_table == "public.docs_v1"
        assert cfg.qualified_chunks_tables == ["public.docs_v1", "public.docs_v2", "public.api_docs"]

    def test_comma_separated_with_spaces(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_CHUNKS_TABLE", "docs_v1 , docs_v2")
        cfg = SteleConfig.from_env()
        assert cfg.chunks_tables == ["docs_v1", "docs_v2"]

    def test_rejects_bad_table_in_multi(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_CHUNKS_TABLE", "good_table,bad table!")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            SteleConfig.from_env()


class TestWritableConfig:
    def test_writable_default_false(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        cfg = SteleConfig.from_env()
        assert cfg.writable is False
        assert cfg.webhook_url is None

    def test_writable_true(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_WRITABLE", "true")
        cfg = SteleConfig.from_env()
        assert cfg.writable is True

    def test_writable_with_webhook(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_WRITABLE", "1")
        monkeypatch.setenv("STELE_WEBHOOK_URL", "https://example.com/hook")
        cfg = SteleConfig.from_env()
        assert cfg.writable is True
        assert cfg.webhook_url == "https://example.com/hook"


class TestFrozen:
    def test_config_is_immutable(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        cfg = SteleConfig.from_env()
        with pytest.raises(AttributeError):
            cfg.schema = "changed"


class TestIdentifierValidation:
    def test_valid_simple_identifier(self):
        assert _validate_identifier("public", "test") == "public"

    def test_valid_qualified_identifier(self):
        assert _validate_identifier("internal.search_docs", "test") == "internal.search_docs"

    def test_valid_underscore_identifier(self):
        assert _validate_identifier("_my_table_2", "test") == "_my_table_2"

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("title; DROP TABLE users--", "test")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("my table", "test")

    def test_rejects_quotes(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("table'name", "test")

    def test_rejects_semicolons(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("a;b", "test")

    def test_rejects_parens(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("func()", "test")

    def test_rejects_leading_digit(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("1table", "test")

    def test_config_rejects_bad_schema(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_SCHEMA", "bad schema!")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            SteleConfig.from_env()

    def test_config_rejects_bad_search_function(self, monkeypatch):
        monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STELE_SEARCH_FUNCTION", "fn(); DROP TABLE--")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            SteleConfig.from_env()
