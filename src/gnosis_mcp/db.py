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


async def _ensure_schema(backend: DocBackend) -> None:
    """Create the schema when the database has none.

    `serve` used to start happily against a database that had never been
    initialised: it advertised every tool and then failed every call with
    `no such table documentation_chunks_fts`. Only `init-db`, `ingest` and `eval`
    ever created the schema, so the documented install order (ingest before serve)
    hid a first run that was broken for anyone who wired the server up first —
    which is what every new MCP client does. One idempotent DDL pass here makes a
    cold start work, and costs a single `check_health` probe when it does not.
    """
    try:
        health = await backend.check_health()
    except Exception:
        log.debug("schema probe failed", exc_info=True)
        return
    if health.get("chunks_table_exists", True):
        return
    try:
        await backend.init_schema()
        log.info("initialised empty database schema")
    except Exception as exc:
        # Read-only credentials are a legitimate PostgreSQL deployment; the call
        # then fails with an accurate error instead of the server refusing to boot.
        log.warning("database schema is missing and could not be created: %s", exc)


@asynccontextmanager
async def app_lifespan(server) -> AsyncIterator[AppContext]:
    """FastMCP lifespan: create backend on startup, close on shutdown."""
    config = GnosisMcpConfig.from_env()
    backend = create_backend(config)

    await backend.startup()

    try:
        await _ensure_schema(backend)
        yield AppContext(backend=backend, config=config)
    finally:
        await backend.shutdown()
