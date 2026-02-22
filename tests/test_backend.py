"""Tests for backend protocol and factory."""

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

    def test_auto_detects_postgres_from_url(self):
        config = GnosisMcpConfig(
            database_url="postgresql://localhost/test", backend="auto"
        )
        assert config.backend == "postgres"
        backend = create_backend(config)
        assert isinstance(backend, DocBackend)
        assert not isinstance(backend, SqliteBackend)

    def test_file_path_resolves_to_sqlite(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        config = GnosisMcpConfig(database_url=db_path, backend="auto")
        assert config.backend == "sqlite"
        backend = create_backend(config)
        assert isinstance(backend, SqliteBackend)

    def test_no_url_resolves_to_sqlite(self):
        config = GnosisMcpConfig(backend="auto")
        assert config.backend == "sqlite"
        backend = create_backend(config)
        assert isinstance(backend, SqliteBackend)
