"""Backend protocol and factory for database abstraction."""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

__all__ = ["DocBackend", "create_backend"]

log = logging.getLogger("gnosis_mcp")


@runtime_checkable
class DocBackend(Protocol):
    """Protocol for documentation storage backends.

    Both PostgreSQL and SQLite backends implement this interface.
    All methods are async to keep the protocol uniform.
    """

    async def startup(self) -> None:
        """Initialize connection pool or database file."""
        ...

    async def shutdown(self) -> None:
        """Close connections and release resources."""
        ...

    async def init_schema(self) -> str:
        """Create tables and indexes. Returns the SQL that was executed."""
        ...

    async def check_health(self) -> dict[str, Any]:
        """Verify database connectivity and schema. Returns status dict."""
        ...

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Search documents. Returns list of {file_path, title, content, category, score, highlight}."""
        ...

    async def get_doc(self, path: str) -> list[dict[str, Any]]:
        """Get all chunks for a document ordered by chunk_index.

        Returns list of {title, content, category, audience, tags, chunk_index}.
        """
        ...

    async def get_related(self, path: str) -> list[dict[str, Any]] | None:
        """Get related documents via links table.

        Returns list of {related_path, relation_type, direction} or None if
        the links table does not exist.
        """
        ...

    async def list_docs(self) -> list[dict[str, Any]]:
        """List all documents with title, category, chunk count.

        Returns list of {file_path, title, category, chunks}.
        """
        ...

    async def list_categories(self) -> list[dict[str, Any]]:
        """List categories with document counts.

        Returns list of {category, docs}.
        """
        ...

    async def upsert_doc(
        self,
        path: str,
        chunks: list[str],
        *,
        title: str | None = None,
        category: str | None = None,
        audience: str = "all",
        tags: list[str] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> int:
        """Insert or replace a document's chunks. Returns number of chunks written."""
        ...

    async def delete_doc(self, path: str) -> dict[str, int]:
        """Delete a document. Returns {chunks_deleted, links_deleted}."""
        ...

    async def update_metadata(
        self,
        path: str,
        *,
        title: str | None = None,
        category: str | None = None,
        audience: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Update metadata on all chunks of a document. Returns rows affected."""
        ...

    async def stats(self) -> dict[str, Any]:
        """Get documentation statistics.

        Returns {table, docs, chunks, content_bytes, categories: [{cat, docs, chunks}],
                 links: int | None}.
        """
        ...

    async def export_docs(self, category: str | None = None) -> list[dict[str, Any]]:
        """Export documents reassembled from chunks.

        Returns list of {file_path, title, category, content}.
        """
        ...

    async def get_pending_embeddings(self, batch_size: int) -> list[dict[str, Any]]:
        """Get chunks with NULL embeddings.

        Returns list of {id, content}.
        """
        ...

    async def count_pending_embeddings(self) -> int:
        """Count chunks with NULL embeddings."""
        ...

    async def set_embedding(self, chunk_id: int, embedding: list[float]) -> None:
        """Set the embedding vector for a chunk."""
        ...

    async def has_column(self, table: str, column: str) -> bool:
        """Check if a column exists on a table."""
        ...

    async def get_content_hash(self, path: str) -> str | None:
        """Get the content_hash for the first chunk of a document, or None."""
        ...

    async def insert_links(
        self,
        source_path: str,
        target_paths: list[str],
        relation_type: str = "relates_to",
    ) -> int:
        """Insert links from source to each target. Returns count inserted."""
        ...

    async def ingest_file(
        self,
        rel_path: str,
        chunks: list[dict[str, str]],
        *,
        title: str,
        category: str,
        audience: str,
        tags: list[str] | None = None,
        content_hash: str | None = None,
        has_tags_col: bool = True,
        has_hash_col: bool = False,
    ) -> int:
        """Ingest a single file's chunks in a transaction. Returns chunk count."""
        ...


def create_backend(config) -> DocBackend:
    """Create the appropriate backend based on config.

    Args:
        config: GnosisMcpConfig instance.

    Returns:
        A DocBackend implementation (PostgresBackend or SqliteBackend).
    """
    from gnosis_mcp.config import GnosisMcpConfig

    assert isinstance(config, GnosisMcpConfig)

    if config.backend == "postgres":
        from gnosis_mcp.pg_backend import PostgresBackend

        return PostgresBackend(config)

    from gnosis_mcp.sqlite_backend import SqliteBackend

    return SqliteBackend(config)
