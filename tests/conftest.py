"""Shared test fixtures for stele tests."""

import pytest

from stele.config import SteleConfig


@pytest.fixture
def default_config(monkeypatch):
    """Config with defaults and a dummy database URL."""
    monkeypatch.setenv("STELE_DATABASE_URL", "postgresql://localhost/test")
    return SteleConfig.from_env()
