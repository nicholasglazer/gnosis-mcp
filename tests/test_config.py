"""Tests for AnsuzConfig."""

import pytest

from ansuz.config import AnsuzConfig, _validate_identifier


class TestFromEnv:
    def test_requires_database_url(self, monkeypatch):
        monkeypatch.delenv("ANSUZ_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValueError, match="DATABASE_URL"):
            AnsuzConfig.from_env()

    def test_ansuz_database_url(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/docs")
        cfg = AnsuzConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/docs"

    def test_fallback_to_database_url(self, monkeypatch):
        monkeypatch.delenv("ANSUZ_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/fallback")
        cfg = AnsuzConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/fallback"

    def test_ansuz_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/ansuz")
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/other")
        cfg = AnsuzConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/ansuz"


class TestDefaults:
    def test_default_schema(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        cfg = AnsuzConfig.from_env()
        assert cfg.schema == "public"
        assert cfg.chunks_table == "documentation_chunks"
        assert cfg.links_table == "documentation_links"
        assert cfg.search_function is None
        assert cfg.embedding_dim == 1536

    def test_qualified_table_names(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_SCHEMA", "internal")
        cfg = AnsuzConfig.from_env()
        assert cfg.qualified_chunks_table == "internal.documentation_chunks"
        assert cfg.qualified_links_table == "internal.documentation_links"


class TestCustomConfig:
    def test_custom_schema_and_tables(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_SCHEMA", "docs")
        monkeypatch.setenv("ANSUZ_CHUNKS_TABLE", "pages")
        monkeypatch.setenv("ANSUZ_LINKS_TABLE", "refs")
        cfg = AnsuzConfig.from_env()
        assert cfg.schema == "docs"
        assert cfg.chunks_table == "pages"
        assert cfg.links_table == "refs"
        assert cfg.qualified_chunks_table == "docs.pages"

    def test_custom_search_function(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_SEARCH_FUNCTION", "internal.search_docs")
        cfg = AnsuzConfig.from_env()
        assert cfg.search_function == "internal.search_docs"

    def test_custom_column_names(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_COL_FILE_PATH", "path")
        monkeypatch.setenv("ANSUZ_COL_CONTENT", "body")
        cfg = AnsuzConfig.from_env()
        assert cfg.col_file_path == "path"
        assert cfg.col_content == "body"

    def test_pool_settings(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_POOL_MIN", "2")
        monkeypatch.setenv("ANSUZ_POOL_MAX", "10")
        cfg = AnsuzConfig.from_env()
        assert cfg.pool_min == 2
        assert cfg.pool_max == 10

    def test_embedding_dim(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_EMBEDDING_DIM", "768")
        cfg = AnsuzConfig.from_env()
        assert cfg.embedding_dim == 768

    def test_invalid_int_env_var(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_POOL_MAX", "abc")
        with pytest.raises(ValueError, match="ANSUZ_POOL_MAX must be an integer"):
            AnsuzConfig.from_env()


class TestFrozen:
    def test_config_is_immutable(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        cfg = AnsuzConfig.from_env()
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
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_SCHEMA", "bad schema!")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            AnsuzConfig.from_env()

    def test_config_rejects_bad_search_function(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("ANSUZ_SEARCH_FUNCTION", "fn(); DROP TABLE--")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            AnsuzConfig.from_env()
