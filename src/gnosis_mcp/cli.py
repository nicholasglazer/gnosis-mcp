"""Command-line interface: serve, init-db, ingest, check."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from gnosis_mcp import __version__

log = logging.getLogger("gnosis_mcp")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.server import mcp

    config = GnosisMcpConfig.from_env()
    transport = args.transport or config.transport
    mcp.run(transport=transport)


def cmd_init_db(args: argparse.Namespace) -> None:
    """Create documentation tables and indexes."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.schema import get_init_sql

    config = GnosisMcpConfig.from_env()
    sql = get_init_sql(config)

    if args.dry_run:
        sys.stdout.write(sql + "\n")
        return

    async def _run() -> None:
        import asyncpg

        conn = await asyncpg.connect(config.database_url)
        try:
            await conn.execute(sql)
            log.info(
                "Created tables in %s: %s, %s, %s.search_%s()",
                config.schema,
                config.qualified_chunks_table,
                config.qualified_links_table,
                config.schema,
                config.chunks_table,
            )
        finally:
            await conn.close()

    asyncio.run(_run())


def cmd_check(args: argparse.Namespace) -> None:
    """Verify database connection and schema."""
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        import asyncpg

        log.info("Connecting to %s ...", _mask_url(config.database_url))
        conn = await asyncpg.connect(config.database_url)
        try:
            # Connection
            version = await conn.fetchval("SELECT version()")
            log.info("PostgreSQL: %s", version.split(",")[0])

            # pgvector
            has_vector = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            log.info("pgvector: %s", "installed" if has_vector else "not installed")

            # Chunks table
            chunks_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                config.schema,
                config.chunks_table,
            )
            if chunks_exists:
                count = await conn.fetchval(
                    f"SELECT count(*) FROM {config.qualified_chunks_table}"
                )
                log.info("%s: %d rows", config.qualified_chunks_table, count)
            else:
                log.warning("%s: does not exist", config.qualified_chunks_table)

            # Links table
            links_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                config.schema,
                config.links_table,
            )
            if links_exists:
                count = await conn.fetchval(
                    f"SELECT count(*) FROM {config.qualified_links_table}"
                )
                log.info("%s: %d rows", config.qualified_links_table, count)
            else:
                log.warning("%s: does not exist", config.qualified_links_table)

            # Custom search function
            if config.search_function:
                fn_schema, fn_name = (
                    config.search_function.split(".", 1)
                    if "." in config.search_function
                    else ("public", config.search_function)
                )
                fn_exists = await conn.fetchval(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.routines"
                    "  WHERE routine_schema = $1 AND routine_name = $2"
                    ")",
                    fn_schema,
                    fn_name,
                )
                if fn_exists:
                    log.info("%s(): found", config.search_function)
                else:
                    log.warning("%s(): NOT FOUND", config.search_function)

            if chunks_exists:
                log.info("All checks passed.")
            else:
                log.info("Run `gnosis-mcp init-db` to create tables.")
        finally:
            await conn.close()

    asyncio.run(_run())


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest markdown files into PostgreSQL."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import ingest_path

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        results = await ingest_path(
            database_url=config.database_url,
            root=args.path,
            schema=config.schema,
            chunks_table=config.chunks_tables[0],
            dry_run=args.dry_run,
        )

        # Print results
        total_chunks = 0
        counts = {"ingested": 0, "unchanged": 0, "skipped": 0, "error": 0, "dry-run": 0}
        for r in results:
            counts[r.action] = counts.get(r.action, 0) + 1
            total_chunks += r.chunks
            marker = {"ingested": "+", "unchanged": "=", "skipped": "-", "error": "!", "dry-run": "?"}
            sym = marker.get(r.action, " ")
            detail = f"  ({r.detail})" if r.detail else ""
            log.info("[%s] %s  (%d chunks)%s", sym, r.path, r.chunks, detail)

        log.info("")
        log.info(
            "Done: %d ingested, %d unchanged, %d skipped, %d errors (%d total chunks)",
            counts["ingested"],
            counts["unchanged"],
            counts["skipped"],
            counts["error"],
            total_chunks,
        )

    asyncio.run(_run())


def _mask_url(url: str) -> str:
    """Mask password in connection URL for display."""
    if ":" not in url or "@" not in url:
        return url
    # postgresql://user:pass@host -> postgresql://user:***@host
    before_at, after_at = url.rsplit("@", 1)
    if ":" in before_at:
        scheme_user, _ = before_at.rsplit(":", 1)
        return f"{scheme_user}:***@{after_at}"
    return url


def main() -> None:
    log_level = os.environ.get("GNOSIS_MCP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        format="%(name)s: %(message)s",
        level=getattr(logging, log_level, logging.INFO),
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        prog="gnosis-mcp",
        description="MCP server for PostgreSQL documentation with pgvector search",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"gnosis-mcp {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start the MCP server")
    p_serve.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="Transport protocol (default: from GNOSIS_MCP_TRANSPORT or stdio)",
    )

    # init-db
    p_init = sub.add_parser("init-db", help="Create documentation tables")
    p_init.add_argument("--dry-run", action="store_true", help="Print SQL without executing")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest markdown files into PostgreSQL")
    p_ingest.add_argument("path", help="File or directory to ingest")
    p_ingest.add_argument("--dry-run", action="store_true", help="Show what would be ingested")

    # check
    sub.add_parser("check", help="Verify database connection and schema")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "serve": cmd_serve,
        "init-db": cmd_init_db,
        "ingest": cmd_ingest,
        "check": cmd_check,
    }
    commands[args.command](args)
