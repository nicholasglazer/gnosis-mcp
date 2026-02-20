"""Tests for db.py — AppContext dataclass and app_lifespan context manager."""

from dataclasses import fields

import pytest

from gnosis_mcp.backend import DocBackend
from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.db import AppContext, app_lifespan
from gnosis_mcp.sqlite_backend import SqliteBackend


class TestAppContext:
    def test_dataclass_fields(self):
        names = {f.name for f in fields(AppContext)}
        assert names == {"backend", "config"}

    def test_holds_backend_and_config(self):
        config = GnosisMcpConfig(database_url=":memory:", backend="sqlite")
        backend = SqliteBackend(config)
        ctx = AppContext(backend=backend, config=config)
        assert ctx.backend is backend
        assert ctx.config is config


class TestAppLifespan:
    @pytest.mark.asyncio
    async def test_yields_app_context(self, monkeypatch):
        """app_lifespan creates backend, yields AppContext, then shuts down."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        async with app_lifespan(None) as ctx:
            assert isinstance(ctx, AppContext)
            assert isinstance(ctx.backend, DocBackend)
            assert ctx.config.backend == "sqlite"

    @pytest.mark.asyncio
    async def test_backend_operational_during_lifespan(self, monkeypatch):
        """Backend is started and usable inside the lifespan context."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        async with app_lifespan(None) as ctx:
            health = await ctx.backend.check_health()
            assert health["backend"] == "sqlite"
