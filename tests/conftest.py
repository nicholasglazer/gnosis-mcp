"""Shared test fixtures for gnosis_mcp tests."""

import pytest

from gnosis_mcp.config import GnosisMcpConfig


@pytest.fixture
def default_config(monkeypatch):
    """Config with defaults and a dummy database URL."""
    monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/test")
    return GnosisMcpConfig.from_env()
