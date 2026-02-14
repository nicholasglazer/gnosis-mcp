"""Database connection pool and FastMCP lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import asyncpg

from ansuz.config import AnsuzConfig


@dataclass
class AppContext:
    """Shared application state for FastMCP tools."""

    pool: asyncpg.Pool
    config: AnsuzConfig


@asynccontextmanager
async def app_lifespan(server) -> AsyncIterator[AppContext]:
    """FastMCP lifespan: create pool on startup, close on shutdown."""
    config = AnsuzConfig.from_env()
    pool = await asyncpg.create_pool(
        config.database_url,
        min_size=config.pool_min,
        max_size=config.pool_max,
    )
    try:
        # Verify connectivity
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        yield AppContext(pool=pool, config=config)
    finally:
        await pool.close()
