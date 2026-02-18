"""Database backend lifecycle and FastMCP lifespan."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from gnosis_mcp.backend import DocBackend, create_backend
from gnosis_mcp.config import GnosisMcpConfig

__all__ = ["AppContext", "app_lifespan"]

log = logging.getLogger("gnosis_mcp")


@dataclass
class AppContext:
    """Shared application state for FastMCP tools."""

    backend: DocBackend
    config: GnosisMcpConfig


@asynccontextmanager
async def app_lifespan(server) -> AsyncIterator[AppContext]:
    """FastMCP lifespan: create backend on startup, close on shutdown."""
    config = GnosisMcpConfig.from_env()
    backend = create_backend(config)

    await backend.startup()

    try:
        yield AppContext(backend=backend, config=config)
    finally:
        await backend.shutdown()
