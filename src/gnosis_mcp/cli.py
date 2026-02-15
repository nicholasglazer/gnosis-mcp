"""Command-line interface: serve, init-db, ingest, search, stats, export, check."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from gnosis_mcp import __version__

__all__ = ["main"]

log = logging.getLogger("gnosis_mcp")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.server import mcp

    config = GnosisMcpConfig.from_env()

    if args.ingest:
        from gnosis_mcp.ingest import ingest_path

        async def _ingest() -> None:
            results = await ingest_path(
                database_url=config.database_url,
                root=args.ingest,
                schema=config.schema,
                chunks_table=config.chunks_tables[0],
            )
            ingested = sum(1 for r in results if r.action == "ingested")
            unchanged = sum(1 for r in results if r.action == "unchanged")
            total = sum(r.chunks for r in results)
            log.info("Ingest: %d new, %d unchanged (%d total chunks)", ingested, unchanged, total)

        asyncio.run(_ingest())

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


def cmd_search(args: argparse.Namespace) -> None:
    """Search documents from the command line."""
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()
    limit = args.limit
    category = args.category

    async def _run() -> None:
        import asyncpg

        conn = await asyncpg.connect(config.database_url)
        try:
            cfg = config
            preview = cfg.content_preview_chars

            if cfg.search_function:
                rows = await conn.fetch(
                    f"SELECT * FROM {cfg.search_function}("
                    f"p_query_text := $1, p_categories := $2, p_limit := $3)",
                    args.query,
                    [category] if category else None,
                    limit,
                )
                for r in rows:
                    score = round(float(r.get("combined_score", 0)), 4)
                    content = r["content"]
                    snippet = content[:preview] + "..." if len(content) > preview else content
                    sys.stdout.write(f"\n  {r['file_path']}  (score: {score})\n")
                    sys.stdout.write(f"  {r['title']}\n")
                    sys.stdout.write(f"  {snippet}\n")
            else:
                select = (
                    f"{cfg.col_file_path}, {cfg.col_title}, {cfg.col_content}, "
                    f"ts_rank({cfg.col_tsv}, websearch_to_tsquery('english', $1)) AS score"
                )
                where = f"{cfg.col_tsv} @@ websearch_to_tsquery('english', $1)"
                if category:
                    where += f" AND {cfg.col_category} = $3"

                sql = (
                    f"SELECT {select} FROM {cfg.qualified_chunks_table} "
                    f"WHERE {where} ORDER BY score DESC LIMIT $2"
                )
                params = [args.query, limit]
                if category:
                    params.append(category)

                rows = await conn.fetch(sql, *params)
                for r in rows:
                    score = round(float(r["score"]), 4)
                    content = r[cfg.col_content]
                    snippet = content[:preview] + "..." if len(content) > preview else content
                    sys.stdout.write(f"\n  {r[cfg.col_file_path]}  (score: {score})\n")
                    sys.stdout.write(f"  {r[cfg.col_title]}\n")
                    sys.stdout.write(f"  {snippet}\n")

            if not rows:
                log.info("No results for: %s", args.query)
            else:
                sys.stdout.write(f"\n  {len(rows)} result(s)\n")

        finally:
            await conn.close()

    asyncio.run(_run())


def cmd_stats(args: argparse.Namespace) -> None:
    """Show documentation statistics."""
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        import asyncpg

        conn = await asyncpg.connect(config.database_url)
        try:
            cfg = config
            qt = cfg.qualified_chunks_table

            # Total chunks
            total = await conn.fetchval(f"SELECT count(*) FROM {qt}")

            # Unique documents
            docs = await conn.fetchval(
                f"SELECT count(DISTINCT {cfg.col_file_path}) FROM {qt}"
            )

            # Categories breakdown
            cats = await conn.fetch(
                f"SELECT {cfg.col_category} AS cat, count(DISTINCT {cfg.col_file_path}) AS docs, "
                f"count(*) AS chunks "
                f"FROM {qt} GROUP BY {cfg.col_category} ORDER BY docs DESC"
            )

            # Total content size
            size = await conn.fetchval(
                f"SELECT coalesce(sum(length({cfg.col_content})), 0) FROM {qt}"
            )

            sys.stdout.write(f"\n  {qt}\n")
            sys.stdout.write(f"  Documents: {docs}\n")
            sys.stdout.write(f"  Chunks:    {total}\n")
            sys.stdout.write(f"  Content:   {_format_bytes(size)}\n\n")

            if cats:
                sys.stdout.write("  Category              Docs  Chunks\n")
                sys.stdout.write("  --------------------  ----  ------\n")
                for r in cats:
                    cat = r["cat"] or "(none)"
                    sys.stdout.write(f"  {cat:<22}{r['docs']:>4}  {r['chunks']:>6}\n")
                sys.stdout.write("\n")

            # Links
            links_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.links_table,
            )
            if links_exists:
                link_count = await conn.fetchval(
                    f"SELECT count(*) FROM {cfg.qualified_links_table}"
                )
                sys.stdout.write(f"  Links: {link_count}\n")
        finally:
            await conn.close()

    asyncio.run(_run())


def cmd_export(args: argparse.Namespace) -> None:
    """Export documents as JSON or markdown."""
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()
    fmt = args.format
    category = args.category

    async def _run() -> None:
        import asyncpg

        conn = await asyncpg.connect(config.database_url)
        try:
            cfg = config
            qt = cfg.qualified_chunks_table

            where = ""
            params: list = []
            if category:
                where = f" WHERE {cfg.col_category} = $1"
                params = [category]

            rows = await conn.fetch(
                f"SELECT {cfg.col_file_path}, {cfg.col_chunk_index}, "
                f"{cfg.col_title}, {cfg.col_content}, {cfg.col_category} "
                f"FROM {qt}{where} "
                f"ORDER BY {cfg.col_file_path}, {cfg.col_chunk_index}",
                *params,
            )

            # Reassemble chunks into documents
            docs: dict[str, dict] = {}
            for r in rows:
                fp = r[cfg.col_file_path]
                if fp not in docs:
                    docs[fp] = {
                        "file_path": fp,
                        "title": r[cfg.col_title],
                        "category": r[cfg.col_category],
                        "content": "",
                    }
                docs[fp]["content"] += r[cfg.col_content] + "\n\n"

            # Strip trailing whitespace
            for d in docs.values():
                d["content"] = d["content"].rstrip()

            if fmt == "json":
                json.dump(list(docs.values()), sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                # markdown: each doc as its own section
                for d in docs.values():
                    sys.stdout.write(f"---\nfile_path: {d['file_path']}\n")
                    sys.stdout.write(f"title: {d['title']}\n")
                    sys.stdout.write(f"category: {d['category']}\n---\n\n")
                    sys.stdout.write(d["content"])
                    sys.stdout.write("\n\n")

            log.info("Exported %d document(s)", len(docs))
        finally:
            await conn.close()

    asyncio.run(_run())


def _format_bytes(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:,.0f} {unit}" if unit == "B" else f"{nbytes:,.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:,.1f} TB"


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
    p_serve.add_argument(
        "--ingest",
        metavar="PATH",
        default=None,
        help="Ingest markdown files from PATH before starting the server",
    )

    # init-db
    p_init = sub.add_parser("init-db", help="Create documentation tables")
    p_init.add_argument("--dry-run", action="store_true", help="Print SQL without executing")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest markdown files into PostgreSQL")
    p_ingest.add_argument("path", help="File or directory to ingest")
    p_ingest.add_argument("--dry-run", action="store_true", help="Show what would be ingested")

    # search
    p_search = sub.add_parser("search", help="Search documents from the command line")
    p_search.add_argument("query", help="Search query text")
    p_search.add_argument("-n", "--limit", type=int, default=5, help="Max results (default: 5)")
    p_search.add_argument("-c", "--category", default=None, help="Filter by category")

    # stats
    sub.add_parser("stats", help="Show documentation statistics")

    # export
    p_export = sub.add_parser("export", help="Export documents as JSON or markdown")
    p_export.add_argument(
        "-f", "--format", choices=["json", "markdown"], default="json", help="Output format (default: json)"
    )
    p_export.add_argument("-c", "--category", default=None, help="Filter by category")

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
        "search": cmd_search,
        "stats": cmd_stats,
        "export": cmd_export,
        "check": cmd_check,
    }
    commands[args.command](args)
