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
        config = GnosisMcpConfig(database_url="postgresql://localhost/test", backend="postgres")
        backend = create_backend(config)
        # Can't import PostgresBackend without asyncpg installed,
        # but it should at least be a DocBackend
        assert isinstance(backend, DocBackend)

    def test_auto_detects_postgres_from_url(self):
        config = GnosisMcpConfig(database_url="postgresql://localhost/test", backend="auto")
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


class _FakePgConn:
    """Records log_access INSERTs; answers the information_schema probes."""

    def __init__(self, columns: set[str]) -> None:
        self._columns = columns
        self.executed: list[tuple[str, tuple]] = []

    async def fetchval(self, sql: str, *args) -> bool:
        return any(f"column_name = '{col}'" in sql for col in self._columns)

    async def execute(self, sql: str, *args) -> None:
        self.executed.append((sql, args))


class _FakeAcquire:
    def __init__(self, conn: _FakePgConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakePgConn:
        return self._conn

    async def __aexit__(self, *exc) -> bool:
        return False


class TestPostgresLogAccess:
    """Postgres log_access feature-detects `client` — no live DB needed."""

    async def _log(self, monkeypatch, columns: set[str], **kwargs) -> _FakePgConn:
        from gnosis_mcp.pg_backend import PostgresBackend

        config = GnosisMcpConfig(database_url="postgresql://localhost/test", backend="postgres")
        backend = PostgresBackend(config)
        conn = _FakePgConn(columns)

        async def _fake_acquire():
            return _FakeAcquire(conn)

        monkeypatch.setattr(backend, "_acquire", _fake_acquire)
        await backend.log_access("a.md", tool="search_docs", **kwargs)
        return conn

    async def test_client_written_when_column_exists(self, monkeypatch):
        conn = await self._log(
            monkeypatch,
            {"tokens_returned", "client"},
            tokens_returned=10,
            tokens_baseline=100,
            client="claude-code/2.1.263",
        )
        (sql, params), *_ = conn.executed
        assert "client" in sql
        assert "$6" in sql  # 6th placeholder is the client value
        assert params == ("a.md", "search_docs", None, 10, 100, "claude-code/2.1.263")

    async def test_null_client_still_inserts(self, monkeypatch):
        conn = await self._log(monkeypatch, {"tokens_returned", "client"}, tokens_returned=10)
        (sql, params), *_ = conn.executed
        assert "client" in sql
        assert params[-1] is None

    async def test_pre_client_schema_falls_back(self, monkeypatch):
        """A DB without the column keeps the old INSERT — client is dropped."""
        conn = await self._log(monkeypatch, {"tokens_returned"}, client="claude-code/2.1.263")
        (sql, params), *_ = conn.executed
        assert "client" not in sql
        assert params == ("a.md", "search_docs", None, None, None)

    async def test_pre_v0_11_8_schema_uses_three_columns(self, monkeypatch):
        conn = await self._log(monkeypatch, set(), client="claude-code/2.1.263")
        (sql, params), *_ = conn.executed
        assert "tokens_returned" not in sql
        assert "client" not in sql
        assert params == ("a.md", "search_docs", None)
