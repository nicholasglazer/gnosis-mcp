"""Configuration via STELE_* environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Valid SQL identifier: letters, digits, underscores. Qualified names allow dots.
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")


def _validate_identifier(value: str, name: str) -> str:
    """Validate a SQL identifier to prevent injection via config values."""
    if not _IDENT_RE.match(value):
        raise ValueError(
            f"Invalid SQL identifier for {name}: {value!r}. "
            "Only letters, digits, underscores, and dots (for qualified names) are allowed."
        )
    return value


@dataclass(frozen=True)
class SteleConfig:
    """Immutable server configuration loaded from environment variables.

    All identifier fields (schema, table names, column names) are validated
    against SQL injection on construction.
    """

    database_url: str

    schema: str = "public"
    chunks_table: str = "documentation_chunks"
    links_table: str = "documentation_links"
    search_function: str | None = None

    # Column name overrides for connecting to an existing table.
    # These do NOT affect `stele init-db` (which always creates standard column names).
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

    # Pool settings
    pool_min: int = 1
    pool_max: int = 3

    # Schema settings
    embedding_dim: int = 1536

    # Write mode (disabled by default -- read-only server)
    writable: bool = False

    # Webhook URL for doc change notifications (optional)
    webhook_url: str | None = None

    def __post_init__(self) -> None:
        """Validate all SQL identifiers after construction."""
        # Validate each chunks table name individually (supports comma-separated)
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
    def from_env(cls) -> SteleConfig:
        """Build config from STELE_* environment variables.

        Falls back to DATABASE_URL if STELE_DATABASE_URL is not set.
        """
        database_url = os.environ.get("STELE_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "Set STELE_DATABASE_URL or DATABASE_URL to a PostgreSQL connection string"
            )

        def env(key: str, default: str | None = None) -> str | None:
            return os.environ.get(f"STELE_{key}", default)

        def env_int(key: str, default: int) -> int:
            val = os.environ.get(f"STELE_{key}")
            if not val:
                return default
            try:
                return int(val)
            except ValueError:
                raise ValueError(f"STELE_{key} must be an integer, got: {val!r}") from None

        return cls(
            database_url=database_url,
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
        )
