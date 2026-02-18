"""Shared test fixtures for gnosis_mcp tests."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig


@pytest.fixture
def default_config(monkeypatch):
    """Config with defaults and a dummy database URL (PostgreSQL)."""
    monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/test")
    return GnosisMcpConfig.from_env()


@pytest.fixture
def sqlite_config(monkeypatch):
    """Config with SQLite backend (no DATABASE_URL needed)."""
    monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return GnosisMcpConfig.from_env()
