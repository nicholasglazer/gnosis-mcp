"""Command-line interface: serve, init-db, check."""

from __future__ import annotations

import argparse
import asyncio
import sys

from stele import __version__


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from stele.server import mcp

    transport = args.transport or "stdio"
    mcp.run(transport=transport)


def cmd_init_db(args: argparse.Namespace) -> None:
    """Create documentation tables and indexes."""
    from stele.config import SteleConfig
    from stele.schema import get_init_sql

    config = SteleConfig.from_env()
    sql = get_init_sql(config)

    if args.dry_run:
        print(sql)
        return

    async def _run() -> None:
        import asyncpg

        conn = await asyncpg.connect(config.database_url)
        try:
            await conn.execute(sql)
            print(f"Created tables in {config.schema}:")
            print(f"  {config.qualified_chunks_table}")
            print(f"  {config.qualified_links_table}")
            print(f"  {config.schema}.search_{config.chunks_table}()")
        finally:
            await conn.close()

    asyncio.run(_run())


def cmd_check(args: argparse.Namespace) -> None:
    """Verify database connection and schema."""
    from stele.config import SteleConfig

    config = SteleConfig.from_env()

    async def _run() -> None:
        import asyncpg

        print(f"Connecting to {_mask_url(config.database_url)} ...")
        conn = await asyncpg.connect(config.database_url)
        try:
            # Connection
            version = await conn.fetchval("SELECT version()")
            print(f"  PostgreSQL: {version.split(',')[0]}")

            # pgvector
            has_vector = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            print(f"  pgvector: {'installed' if has_vector else 'not installed'}")

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
                print(f"  {config.qualified_chunks_table}: {count} rows")
            else:
                print(f"  {config.qualified_chunks_table}: does not exist")

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
                print(f"  {config.qualified_links_table}: {count} rows")
            else:
                print(f"  {config.qualified_links_table}: does not exist")

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
                print(
                    f"  {config.search_function}(): "
                    f"{'found' if fn_exists else 'NOT FOUND'}"
                )

            print("\nAll checks passed." if chunks_exists else "\nRun `stele init-db` to create tables.")
        finally:
            await conn.close()

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
    parser = argparse.ArgumentParser(
        prog="stele",
        description="MCP server for PostgreSQL documentation with pgvector search",
    )
    parser.add_argument("-V", "--version", action="version", version=f"stele {__version__}")
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start the MCP server")
    p_serve.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )

    # init-db
    p_init = sub.add_parser("init-db", help="Create documentation tables")
    p_init.add_argument("--dry-run", action="store_true", help="Print SQL without executing")

    # check
    sub.add_parser("check", help="Verify database connection and schema")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "serve": cmd_serve,
        "init-db": cmd_init_db,
        "check": cmd_check,
    }
    commands[args.command](args)
