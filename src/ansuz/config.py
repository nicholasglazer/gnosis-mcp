"""Configuration via ANSUZ_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AnsuzConfig:
    """Immutable server configuration loaded from environment variables."""

    database_url: str

    schema: str = "public"
    chunks_table: str = "documentation_chunks"
    links_table: str = "documentation_links"
    search_function: str | None = None

    # Column names (override if your table uses different names)
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

    @property
    def qualified_chunks_table(self) -> str:
        return f"{self.schema}.{self.chunks_table}"

    @property
    def qualified_links_table(self) -> str:
        return f"{self.schema}.{self.links_table}"

    @classmethod
    def from_env(cls) -> AnsuzConfig:
        """Build config from ANSUZ_* environment variables.

        Falls back to DATABASE_URL if ANSUZ_DATABASE_URL is not set.
        """
        database_url = os.environ.get("ANSUZ_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "Set ANSUZ_DATABASE_URL or DATABASE_URL to a PostgreSQL connection string"
            )

        def env(key: str, default: str | None = None) -> str | None:
            return os.environ.get(f"ANSUZ_{key}", default)

        def env_int(key: str, default: int) -> int:
            val = os.environ.get(f"ANSUZ_{key}")
            return int(val) if val else default

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
        )
