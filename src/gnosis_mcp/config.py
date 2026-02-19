"""Configuration via GNOSIS_MCP_* environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Valid SQL identifier: letters, digits, underscores. Qualified names allow dots.
__all__ = ["GnosisMcpConfig"]

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")

_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_VALID_TRANSPORTS = ("stdio", "sse")
_VALID_EMBED_PROVIDERS = ("openai", "ollama", "custom", "local")
_VALID_BACKENDS = ("auto", "sqlite", "postgres")


def _validate_identifier(value: str, name: str) -> str:
    """Validate a SQL identifier to prevent injection via config values."""
    if not _IDENT_RE.match(value):
        raise ValueError(
            f"Invalid SQL identifier for {name}: {value!r}. "
            "Only letters, digits, underscores, and dots (for qualified names) are allowed."
        )
    return value


def _resolve_sqlite_path() -> str:
    """Resolve the default SQLite database path using XDG conventions."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".local" / "share"
    return str(base / "gnosis-mcp" / "docs.db")


@dataclass(frozen=True)
class GnosisMcpConfig:
    """Immutable server configuration loaded from environment variables.

    All identifier fields (schema, table names, column names) are validated
    against SQL injection on construction.
    """

    database_url: str | None = None

    # Backend selection: "auto", "sqlite", "postgres"
    backend: str = "auto"

    schema: str = "public"
    chunks_table: str = "documentation_chunks"
    links_table: str = "documentation_links"
    search_function: str | None = None

    # Column name overrides for connecting to an existing table.
    # These do NOT affect `gnosis-mcp init-db` (which always creates standard column names).
    col_file_path: str = "file_path"
    col_title: str = "title"
    col_content: str = "content"
    col_chunk_index: str = "chunk_index"
    col_category: str = "category"
    col_audience: str = "audience"
    col_tags: str = "tags"
    col_embedding: str = "embedding"
    col_tsv: str = "tsv"

    # Link columns
    col_source_path: str = "source_path"
    col_target_path: str = "target_path"
    col_relation_type: str = "relation_type"

    # Pool settings (PostgreSQL only)
    pool_min: int = 1
    pool_max: int = 3

    # Schema settings
    embedding_dim: int = 1536

    # Write mode (disabled by default -- read-only server)
    writable: bool = False

    # Webhook URL for doc change notifications (optional)
    webhook_url: str | None = None

    # Tuning knobs
    content_preview_chars: int = 200
    chunk_size: int = 4000
    search_limit_max: int = 20
    webhook_timeout: int = 5

    # Embedding provider (Tier 2 sidecar)
    embed_provider: str | None = None  # "openai", "ollama", "custom", "local"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 384  # Matryoshka truncation dim for local provider, vec0 column width
    embed_api_key: str | None = None
    embed_url: str | None = None  # custom endpoint or ollama override
    embed_batch_size: int = 50

    # Server defaults
    transport: str = "stdio"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Validate all SQL identifiers and tuning parameters after construction."""
        # Resolve backend from "auto"
        if self.backend == "auto":
            resolved = self._detect_backend()
            object.__setattr__(self, "backend", resolved)

        if self.backend not in ("sqlite", "postgres"):
            raise ValueError(
                f"GNOSIS_MCP_BACKEND must resolve to 'sqlite' or 'postgres', got {self.backend!r}"
            )

        # For sqlite, set default path if database_url is None
        if self.backend == "sqlite" and self.database_url is None:
            object.__setattr__(self, "database_url", _resolve_sqlite_path())

        # For postgres, database_url is required
        if self.backend == "postgres" and not self.database_url:
            raise ValueError(
                "PostgreSQL backend requires GNOSIS_MCP_DATABASE_URL or DATABASE_URL"
            )

        # Validate identifiers (relevant for both backends, harmless for SQLite)
        for table_name in self.chunks_tables:
            _validate_identifier(table_name, "chunks_table")

        identifiers = {
            "schema": self.schema,
            "links_table": self.links_table,
            "col_file_path": self.col_file_path,
            "col_title": self.col_title,
            "col_content": self.col_content,
            "col_chunk_index": self.col_chunk_index,
            "col_category": self.col_category,
            "col_audience": self.col_audience,
            "col_tags": self.col_tags,
            "col_embedding": self.col_embedding,
            "col_tsv": self.col_tsv,
            "col_source_path": self.col_source_path,
            "col_target_path": self.col_target_path,
            "col_relation_type": self.col_relation_type,
        }
        for name, value in identifiers.items():
            _validate_identifier(value, name)

        if self.search_function is not None:
            _validate_identifier(self.search_function, "search_function")

        # Validate tuning knobs
        if self.content_preview_chars < 50:
            raise ValueError(
                f"GNOSIS_MCP_CONTENT_PREVIEW_CHARS must be >= 50, got {self.content_preview_chars}"
            )
        if self.chunk_size < 500:
            raise ValueError(f"GNOSIS_MCP_CHUNK_SIZE must be >= 500, got {self.chunk_size}")
        if self.search_limit_max < 1:
            raise ValueError(
                f"GNOSIS_MCP_SEARCH_LIMIT_MAX must be >= 1, got {self.search_limit_max}"
            )
        if self.webhook_timeout < 1:
            raise ValueError(
                f"GNOSIS_MCP_WEBHOOK_TIMEOUT must be >= 1, got {self.webhook_timeout}"
            )
        if self.transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"GNOSIS_MCP_TRANSPORT must be one of {_VALID_TRANSPORTS}, got {self.transport!r}"
            )
        if self.log_level not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"GNOSIS_MCP_LOG_LEVEL must be one of {_VALID_LOG_LEVELS}, got {self.log_level!r}"
            )
        if self.embed_provider is not None and self.embed_provider not in _VALID_EMBED_PROVIDERS:
            raise ValueError(
                f"GNOSIS_MCP_EMBED_PROVIDER must be one of {_VALID_EMBED_PROVIDERS}, "
                f"got {self.embed_provider!r}"
            )
        if self.embed_batch_size < 1:
            raise ValueError(
                f"GNOSIS_MCP_EMBED_BATCH_SIZE must be >= 1, got {self.embed_batch_size}"
            )

    def _detect_backend(self) -> str:
        """Auto-detect backend from database_url."""
        url = self.database_url
        if url is None:
            return "sqlite"
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            return "postgres"
        # Treat any other URL as a SQLite file path
        return "sqlite"

    @property
    def chunks_tables(self) -> list[str]:
        """Split comma-separated chunks_table into a list."""
        return [t.strip() for t in self.chunks_table.split(",") if t.strip()]

    @property
    def qualified_chunks_table(self) -> str:
        """Primary chunks table (first in the list)."""
        return f"{self.schema}.{self.chunks_tables[0]}"

    @property
    def qualified_chunks_tables(self) -> list[str]:
        """All qualified chunks table names."""
        return [f"{self.schema}.{t}" for t in self.chunks_tables]

    @property
    def multi_table(self) -> bool:
        """True if configured with multiple chunks tables."""
        return len(self.chunks_tables) > 1

    @property
    def qualified_links_table(self) -> str:
        return f"{self.schema}.{self.links_table}"

    @classmethod
    def from_env(cls) -> GnosisMcpConfig:
        """Build config from GNOSIS_MCP_* environment variables.

        Falls back to DATABASE_URL if GNOSIS_MCP_DATABASE_URL is not set.
        When neither is set, defaults to SQLite at ~/.local/share/gnosis-mcp/docs.db.
        """
        database_url = os.environ.get("GNOSIS_MCP_DATABASE_URL") or os.environ.get(
            "DATABASE_URL"
        )
        # database_url can be None — that means SQLite default

        def env(key: str, default: str | None = None) -> str | None:
            return os.environ.get(f"GNOSIS_MCP_{key}", default)

        def env_int(key: str, default: int) -> int:
            val = os.environ.get(f"GNOSIS_MCP_{key}")
            if not val:
                return default
            try:
                return int(val)
            except ValueError:
                raise ValueError(
                    f"GNOSIS_MCP_{key} must be an integer, got: {val!r}"
                ) from None

        backend_raw = env("BACKEND", "auto")

        return cls(
            database_url=database_url if database_url else None,
            backend=backend_raw,
            schema=env("SCHEMA", "public"),
            chunks_table=env("CHUNKS_TABLE", "documentation_chunks"),
            links_table=env("LINKS_TABLE", "documentation_links"),
            search_function=env("SEARCH_FUNCTION"),
            col_file_path=env("COL_FILE_PATH", "file_path"),
            col_title=env("COL_TITLE", "title"),
            col_content=env("COL_CONTENT", "content"),
            col_chunk_index=env("COL_CHUNK_INDEX", "chunk_index"),
            col_category=env("COL_CATEGORY", "category"),
            col_audience=env("COL_AUDIENCE", "audience"),
            col_tags=env("COL_TAGS", "tags"),
            col_embedding=env("COL_EMBEDDING", "embedding"),
            col_tsv=env("COL_TSV", "tsv"),
            col_source_path=env("COL_SOURCE_PATH", "source_path"),
            col_target_path=env("COL_TARGET_PATH", "target_path"),
            col_relation_type=env("COL_RELATION_TYPE", "relation_type"),
            pool_min=env_int("POOL_MIN", 1),
            pool_max=env_int("POOL_MAX", 3),
            embedding_dim=env_int("EMBEDDING_DIM", 1536),
            writable=env("WRITABLE", "").lower() in ("1", "true", "yes"),
            webhook_url=env("WEBHOOK_URL"),
            content_preview_chars=env_int("CONTENT_PREVIEW_CHARS", 200),
            chunk_size=env_int("CHUNK_SIZE", 4000),
            search_limit_max=env_int("SEARCH_LIMIT_MAX", 20),
            webhook_timeout=env_int("WEBHOOK_TIMEOUT", 5),
            embed_provider=env("EMBED_PROVIDER"),
            embed_model=env("EMBED_MODEL", "text-embedding-3-small"),
            embed_dim=env_int("EMBED_DIM", 384),
            embed_api_key=env("EMBED_API_KEY"),
            embed_url=env("EMBED_URL"),
            embed_batch_size=env_int("EMBED_BATCH_SIZE", 50),
            transport=env("TRANSPORT", "stdio"),
            log_level=env("LOG_LEVEL", "INFO").upper(),
        )
