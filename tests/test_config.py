"""Tests for GnosisMcpConfig."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig, _validate_identifier


class TestFromEnv:
    def test_no_url_defaults_to_sqlite(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        cfg = GnosisMcpConfig.from_env()
        assert cfg.backend == "sqlite"
        assert cfg.database_url.endswith("gnosis-mcp/docs.db")

    def test_gnosis_mcp_database_url(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/docs")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/docs"
        assert cfg.backend == "postgres"

    def test_fallback_to_database_url(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/fallback")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/fallback"
        assert cfg.backend == "postgres"

    def test_gnosis_mcp_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/gnosis")
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/other")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.database_url == "postgresql://localhost/gnosis"


class TestBackendDetection:
    def test_auto_postgres_from_url(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.backend == "postgres"

    def test_auto_sqlite_no_url(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        cfg = GnosisMcpConfig.from_env()
        assert cfg.backend == "sqlite"

    def test_explicit_sqlite(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_BACKEND", "sqlite")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.backend == "sqlite"

    def test_explicit_postgres_requires_url(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_BACKEND", "postgres")
        with pytest.raises(ValueError, match="PostgreSQL backend requires"):
            GnosisMcpConfig.from_env()

    def test_sqlite_default_path_xdg(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/test-xdg")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.database_url == "/tmp/test-xdg/gnosis-mcp/docs.db"

    def test_auto_sqlite_for_file_path(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "/path/to/my.db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.backend == "sqlite"
        assert cfg.database_url == "/path/to/my.db"


class TestDefaults:
    def test_default_schema(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.schema == "public"
        assert cfg.chunks_table == "documentation_chunks"
        assert cfg.links_table == "documentation_links"
        assert cfg.search_function is None
        assert cfg.embedding_dim == 1536

    def test_qualified_table_names(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SCHEMA", "internal")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.qualified_chunks_table == "internal.documentation_chunks"
        assert cfg.qualified_links_table == "internal.documentation_links"


class TestCustomConfig:
    def test_custom_schema_and_tables(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SCHEMA", "docs")
        monkeypatch.setenv("GNOSIS_MCP_CHUNKS_TABLE", "pages")
        monkeypatch.setenv("GNOSIS_MCP_LINKS_TABLE", "refs")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.schema == "docs"
        assert cfg.chunks_table == "pages"
        assert cfg.links_table == "refs"
        assert cfg.qualified_chunks_table == "docs.pages"

    def test_custom_search_function(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_FUNCTION", "internal.search_docs")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.search_function == "internal.search_docs"

    def test_custom_column_names(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_COL_FILE_PATH", "path")
        monkeypatch.setenv("GNOSIS_MCP_COL_CONTENT", "body")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.col_file_path == "path"
        assert cfg.col_content == "body"

    def test_pool_settings(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_POOL_MIN", "2")
        monkeypatch.setenv("GNOSIS_MCP_POOL_MAX", "10")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.pool_min == 2
        assert cfg.pool_max == 10

    def test_embedding_dim(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBEDDING_DIM", "768")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embedding_dim == 768

    def test_invalid_int_env_var(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_POOL_MAX", "abc")
        with pytest.raises(ValueError, match="GNOSIS_MCP_POOL_MAX must be an integer"):
            GnosisMcpConfig.from_env()


class TestMultiTable:
    def test_single_table(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.chunks_tables == ["documentation_chunks"]
        assert not cfg.multi_table
        assert cfg.qualified_chunks_table == "public.documentation_chunks"

    def test_comma_separated_tables(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CHUNKS_TABLE", "docs_v1,docs_v2,api_docs")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.chunks_tables == ["docs_v1", "docs_v2", "api_docs"]
        assert cfg.multi_table
        assert cfg.qualified_chunks_table == "public.docs_v1"
        assert cfg.qualified_chunks_tables == [
            "public.docs_v1",
            "public.docs_v2",
            "public.api_docs",
        ]

    def test_comma_separated_with_spaces(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CHUNKS_TABLE", "docs_v1 , docs_v2")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.chunks_tables == ["docs_v1", "docs_v2"]

    def test_rejects_bad_table_in_multi(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CHUNKS_TABLE", "good_table,bad table!")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            GnosisMcpConfig.from_env()


class TestWritableConfig:
    def test_writable_default_false(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.writable is False
        assert cfg.webhook_url is None

    def test_writable_true(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_WRITABLE", "true")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.writable is True

    def test_writable_with_webhook(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_WRITABLE", "1")
        monkeypatch.setenv("GNOSIS_MCP_WEBHOOK_URL", "https://example.com/hook")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.writable is True
        assert cfg.webhook_url == "https://example.com/hook"


class TestTuningConfig:
    def test_tuning_defaults(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.content_preview_chars == 200
        assert cfg.chunk_size == 2000
        assert cfg.search_limit_max == 20
        assert cfg.webhook_timeout == 5
        assert cfg.transport == "stdio"
        assert cfg.log_level == "INFO"

    def test_custom_content_preview_chars(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CONTENT_PREVIEW_CHARS", "100")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.content_preview_chars == 100

    def test_custom_chunk_size(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CHUNK_SIZE", "8000")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.chunk_size == 8000

    def test_custom_search_limit_max(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "50")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.search_limit_max == 50

    def test_custom_webhook_timeout(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_WEBHOOK_TIMEOUT", "10")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.webhook_timeout == 10

    def test_custom_transport(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_TRANSPORT", "sse")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.transport == "sse"

    def test_custom_log_level(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_LOG_LEVEL", "debug")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.log_level == "DEBUG"

    def test_rejects_low_content_preview_chars(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CONTENT_PREVIEW_CHARS", "10")
        with pytest.raises(ValueError, match="GNOSIS_MCP_CONTENT_PREVIEW_CHARS must be >= 50"):
            GnosisMcpConfig.from_env()

    def test_rejects_low_chunk_size(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_CHUNK_SIZE", "100")
        with pytest.raises(ValueError, match="GNOSIS_MCP_CHUNK_SIZE must be >= 500"):
            GnosisMcpConfig.from_env()

    def test_rejects_zero_search_limit(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "0")
        with pytest.raises(ValueError, match="GNOSIS_MCP_SEARCH_LIMIT_MAX must be >= 1"):
            GnosisMcpConfig.from_env()

    def test_rejects_zero_webhook_timeout(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_WEBHOOK_TIMEOUT", "0")
        with pytest.raises(ValueError, match="GNOSIS_MCP_WEBHOOK_TIMEOUT must be >= 1"):
            GnosisMcpConfig.from_env()

    def test_rejects_invalid_transport(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_TRANSPORT", "http")
        with pytest.raises(ValueError, match="GNOSIS_MCP_TRANSPORT must be one of"):
            GnosisMcpConfig.from_env()

    def test_rejects_invalid_log_level(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_LOG_LEVEL", "VERBOSE")
        with pytest.raises(ValueError, match="GNOSIS_MCP_LOG_LEVEL must be one of"):
            GnosisMcpConfig.from_env()


class TestFrozen:
    def test_config_is_immutable(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
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
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SCHEMA", "bad schema!")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            GnosisMcpConfig.from_env()

    def test_config_rejects_bad_search_function(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_FUNCTION", "fn(); DROP TABLE--")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            GnosisMcpConfig.from_env()


class TestEmbedConfig:
    def test_embed_defaults(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider is None
        assert cfg.embed_model == "text-embedding-3-small"
        assert cfg.embed_api_key is None
        assert cfg.embed_url is None
        assert cfg.embed_batch_size == 50
        assert cfg.embed_dim == 384

    def test_embed_provider_local(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "local")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider == "local"

    def test_local_provider_swaps_default_model(self, monkeypatch):
        """Regression: provider=local with no explicit model must not keep the OpenAI default.

        Pre-fix: auto-embed passed `text-embedding-3-small` into LocalEmbedder,
        which treated it as a HuggingFace repo id and got a 401. Post-fix: the
        config swaps in `MongoDB/mdbr-leaf-ir` during __post_init__ so every
        downstream caller sees the right default.
        """
        monkeypatch.delenv("GNOSIS_MCP_EMBED_MODEL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "local")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider == "local"
        assert cfg.embed_model == "MongoDB/mdbr-leaf-ir"

    def test_local_provider_preserves_explicit_model(self, monkeypatch):
        """User-set EMBED_MODEL takes precedence even when provider=local."""
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "local")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_MODEL", "intfloat/e5-small-v2")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_model == "intfloat/e5-small-v2"

    def test_openai_provider_keeps_openai_default(self, monkeypatch):
        """Swap is scoped to provider=local — openai keeps its own default."""
        monkeypatch.delenv("GNOSIS_MCP_EMBED_MODEL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "openai")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_model == "text-embedding-3-small"

    def test_collapse_by_doc_default_off(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MCP_COLLAPSE_BY_DOC", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.collapse_by_doc is False

    def test_collapse_by_doc_opt_in(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_COLLAPSE_BY_DOC", "true")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.collapse_by_doc is True

    def test_fts5_weights_default_preserves_title_boost(self, monkeypatch):
        """Defaults match the previous hardcoded 10:1 ratio — no surprise regression on upgrade."""
        monkeypatch.delenv("GNOSIS_MCP_FTS5_TITLE_WEIGHT", raising=False)
        monkeypatch.delenv("GNOSIS_MCP_FTS5_CONTENT_WEIGHT", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.fts5_title_weight == 10.0
        assert cfg.fts5_content_weight == 1.0

    def test_fts5_weights_override(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_FTS5_TITLE_WEIGHT", "5.5")
        monkeypatch.setenv("GNOSIS_MCP_FTS5_CONTENT_WEIGHT", "2.0")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.fts5_title_weight == 5.5
        assert cfg.fts5_content_weight == 2.0

    def test_fts5_weights_bad_input_raises(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_FTS5_TITLE_WEIGHT", "not-a-number")
        with pytest.raises(ValueError, match="FTS5_TITLE_WEIGHT"):
            GnosisMcpConfig.from_env()

    def test_mmr_lambda_default_off(self, monkeypatch):
        """Default λ=1.0 — MMR off, existing rankings untouched on upgrade."""
        monkeypatch.delenv("GNOSIS_MCP_MMR_LAMBDA", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.mmr_lambda == 1.0

    def test_mmr_lambda_typical_value(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_MMR_LAMBDA", "0.6")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.mmr_lambda == 0.6

    def test_mmr_lambda_out_of_range_rejected(self, monkeypatch):
        """Values outside [0,1] almost always mean a typo — fail loudly."""
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_MMR_LAMBDA", "1.5")
        with pytest.raises(ValueError, match="MMR_LAMBDA"):
            GnosisMcpConfig.from_env()

    def test_embed_dim_default(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_dim == 384

    def test_custom_embed_dim(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_DIM", "768")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_dim == 768

    def test_host_port_defaults(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000

    def test_custom_host_port(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("GNOSIS_MCP_PORT", "9000")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000

    def test_embed_provider_openai(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "openai")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider == "openai"

    def test_embed_provider_ollama(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "ollama")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider == "ollama"

    def test_embed_provider_custom(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "custom")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider == "custom"

    def test_rejects_invalid_embed_provider(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "gemini")
        with pytest.raises(ValueError, match="GNOSIS_MCP_EMBED_PROVIDER must be one of"):
            GnosisMcpConfig.from_env()

    def test_custom_embed_model(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_MODEL", "nomic-embed-text")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_model == "nomic-embed-text"

    def test_embed_api_key(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_API_KEY", "sk-test-key")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_api_key == "sk-test-key"

    def test_custom_embed_url(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_URL", "https://my-embed.com/v1/embed")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_url == "https://my-embed.com/v1/embed"

    def test_custom_embed_batch_size(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_BATCH_SIZE", "25")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_batch_size == 25

    def test_rejects_zero_embed_batch_size(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_BATCH_SIZE", "0")
        with pytest.raises(ValueError, match="GNOSIS_MCP_EMBED_BATCH_SIZE must be >= 1"):
            GnosisMcpConfig.from_env()

    def test_full_embed_config(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "openai")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_MODEL", "text-embedding-3-large")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_API_KEY", "sk-xyz")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_URL", "https://custom.openai.com/v1/embeddings")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_BATCH_SIZE", "100")
        cfg = GnosisMcpConfig.from_env()
        assert cfg.embed_provider == "openai"
        assert cfg.embed_model == "text-embedding-3-large"
        assert cfg.embed_api_key == "sk-xyz"
        assert cfg.embed_url == "https://custom.openai.com/v1/embeddings"
        assert cfg.embed_batch_size == 100
