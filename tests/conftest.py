"""Shared test fixtures for ansuz tests."""

import pytest

from ansuz.config import AnsuzConfig


@pytest.fixture
def default_config(monkeypatch):
    """Config with defaults and a dummy database URL."""
    monkeypatch.setenv("ANSUZ_DATABASE_URL", "postgresql://localhost/test")
    return AnsuzConfig.from_env()
