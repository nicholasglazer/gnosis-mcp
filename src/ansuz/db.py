"""Database connection pool and FastMCP lifespan."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import asyncpg

from ansuz.config import AnsuzConfig

log = logging.getLogger("ansuz")


@dataclass
class AppContext:
    """Shared application state for FastMCP tools."""

    pool: asyncpg.Pool
    config: AnsuzConfig


@asynccontextmanager
async def app_lifespan(server) -> AsyncIterator[AppContext]:
    """FastMCP lifespan: create pool on startup, close on shutdown."""
    config = AnsuzConfig.from_env()

    try:
        pool = await asyncpg.create_pool(
            config.database_url,
            min_size=config.pool_min,
            max_size=config.pool_max,
        )
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"ansuz: failed to connect to database: {exc}", file=sys.stderr)
        print("ansuz: check ANSUZ_DATABASE_URL and ensure PostgreSQL is running", file=sys.stderr)
        raise SystemExit(1) from exc

    log.info(
        "ansuz started: schema=%s chunks=%s links=%s search_fn=%s",
        config.schema,
        config.chunks_table,
        config.links_table,
        config.search_function or "(built-in tsvector)",
    )

    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        yield AppContext(pool=pool, config=config)
    finally:
        await pool.close()
