"""Tests for AnsuzConfig."""

import os

import pytest

from ansuz.config import AnsuzConfig


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


class TestFrozen:
    def test_config_is_immutable(self, monkeypatch):
        monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/db")
        cfg = AnsuzConfig.from_env()
        with pytest.raises(AttributeError):
            cfg.schema = "changed"
