"""Tests for backend protocol and factory."""

import pytest

from gnosis_mcp.backend import DocBackend, create_backend
from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.sqlite_backend import SqliteBackend


class TestDocBackendProtocol:
    def test_sqlite_backend_is_doc_backend(self):
        config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
        backend = SqliteBackend(config)
        assert isinstance(backend, DocBackend)

    def test_create_backend_sqlite(self):
        config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
        backend = create_backend(config)
        assert isinstance(backend, SqliteBackend)
        assert isinstance(backend, DocBackend)

    def test_create_backend_auto_sqlite(self):
        config = GnosisMcpConfig(backend="auto")
        backend = create_backend(config)
        assert isinstance(backend, SqliteBackend)

    def test_create_backend_postgres(self):
        config = GnosisMcpConfig(
            database_url="postgresql://localhost/test", backend="postgres"
        )
        backend = create_backend(config)
        # Can't import PostgresBackend without asyncpg installed,
        # but it should at least be a DocBackend
        assert isinstance(backend, DocBackend)
