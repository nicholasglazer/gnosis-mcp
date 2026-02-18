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
                config=config,
                root=args.ingest,
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
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    if args.dry_run:
        if config.backend == "postgres":
            from gnosis_mcp.schema import get_init_sql
            sys.stdout.write(get_init_sql(config) + "\n")
        else:
            from gnosis_mcp.sqlite_schema import get_sqlite_schema
            sys.stdout.write("\n".join(get_sqlite_schema()) + "\n")
        return

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            sql = await backend.init_schema()
            log.info("Schema initialized (%s backend)", config.backend)
        finally:
            await backend.shutdown()

    asyncio.run(_run())


def cmd_check(args: argparse.Namespace) -> None:
    """Verify database connection and schema."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            health = await backend.check_health()

            log.info("Backend: %s", health.get("backend"))
            log.info("Version: %s", health.get("version", "unknown"))

            if "pgvector" in health:
                log.info("pgvector: %s", "installed" if health["pgvector"] else "not installed")

            if "fts_table_exists" in health:
                log.info("FTS5: %s", "ready" if health["fts_table_exists"] else "not initialized")

            if health.get("chunks_table_exists"):
                log.info("Chunks: %d rows", health.get("chunks_count", 0))
            else:
                log.warning("Chunks table: does not exist")

            if health.get("links_table_exists"):
                log.info("Links: %d rows", health.get("links_count", 0))

            if health.get("search_function_exists") is not None:
                fn_status = "found" if health["search_function_exists"] else "NOT FOUND"
                log.info("Search function: %s", fn_status)

            if health.get("path"):
                log.info("Database: %s", health["path"])

            if health.get("chunks_table_exists"):
                log.info("All checks passed.")
            else:
                log.info("Run `gnosis-mcp init-db` to create tables.")
        finally:
            await backend.shutdown()

    asyncio.run(_run())


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest markdown files into the database."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import ingest_path

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        results = await ingest_path(
            config=config,
            root=args.path,
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
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()
    limit = args.limit
    category = args.category
    use_embed = getattr(args, "embed", False)
    preview = config.content_preview_chars

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            query_embedding = None
            if use_embed:
                provider = config.embed_provider
                if not provider:
                    log.error("--embed requires GNOSIS_MCP_EMBED_PROVIDER to be set")
                    return
                from gnosis_mcp.embed import embed_texts

                vectors = embed_texts(
                    [args.query],
                    provider=provider,
                    model=config.embed_model,
                    api_key=config.embed_api_key,
                    url=config.embed_url,
                )
                query_embedding = vectors[0] if vectors else None

            results = await backend.search(
                args.query,
                category=category,
                limit=limit,
                query_embedding=query_embedding,
            )

            for r in results:
                score = round(float(r["score"]), 4)
                content = r["content"]
                snippet = content[:preview] + "..." if len(content) > preview else content
                sys.stdout.write(f"\n  {r['file_path']}  (score: {score})\n")
                sys.stdout.write(f"  {r['title']}\n")
                sys.stdout.write(f"  {snippet}\n")

            if not results:
                log.info("No results for: %s", args.query)
            else:
                sys.stdout.write(f"\n  {len(results)} result(s)\n")
        finally:
            await backend.shutdown()

    asyncio.run(_run())


def cmd_embed(args: argparse.Namespace) -> None:
    """Embed chunks with NULL embeddings using a configured provider."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.embed import embed_pending

    config = GnosisMcpConfig.from_env()
    provider = args.provider or config.embed_provider
    if not provider:
        log.error(
            "No embedding provider configured. "
            "Set GNOSIS_MCP_EMBED_PROVIDER or use --provider."
        )
        sys.exit(1)

    model = args.model or config.embed_model
    batch_size = args.batch_size or config.embed_batch_size
    api_key = config.embed_api_key
    url = config.embed_url

    async def _run() -> None:
        result = await embed_pending(
            config=config,
            provider=provider,
            model=model,
            api_key=api_key,
            url=url,
            batch_size=batch_size,
            dry_run=args.dry_run,
        )

        if args.dry_run:
            sys.stdout.write(f"\n  Chunks with NULL embeddings: {result.total_null}\n")
            sys.stdout.write("  (dry run — no embeddings created)\n\n")
        else:
            sys.stdout.write(f"\n  Embedded: {result.embedded}/{result.total_null} chunks\n")
            if result.errors:
                sys.stdout.write(f"  Errors: {result.errors}\n")
            sys.stdout.write("\n")

    asyncio.run(_run())


def cmd_stats(args: argparse.Namespace) -> None:
    """Show documentation statistics."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            s = await backend.stats()

            sys.stdout.write(f"\n  {s['table']}\n")
            sys.stdout.write(f"  Documents: {s['docs']}\n")
            sys.stdout.write(f"  Chunks:    {s['chunks']}\n")
            sys.stdout.write(f"  Content:   {_format_bytes(s['content_bytes'])}\n\n")

            cats = s.get("categories", [])
            if cats:
                sys.stdout.write("  Category              Docs  Chunks\n")
                sys.stdout.write("  --------------------  ----  ------\n")
                for r in cats:
                    cat = r["cat"] or "(none)"
                    sys.stdout.write(f"  {cat:<22}{r['docs']:>4}  {r['chunks']:>6}\n")
                sys.stdout.write("\n")

            if s.get("links") is not None:
                sys.stdout.write(f"  Links: {s['links']}\n")
        finally:
            await backend.shutdown()

    asyncio.run(_run())


def cmd_export(args: argparse.Namespace) -> None:
    """Export documents as JSON or markdown."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()
    fmt = args.format
    category = args.category

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            docs = await backend.export_docs(category=category)

            if fmt == "json":
                json.dump(docs, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                for d in docs:
                    sys.stdout.write(f"---\nfile_path: {d['file_path']}\n")
                    sys.stdout.write(f"title: {d['title']}\n")
                    sys.stdout.write(f"category: {d['category']}\n---\n\n")
                    sys.stdout.write(d["content"])
                    sys.stdout.write("\n\n")

            log.info("Exported %d document(s)", len(docs))
        finally:
            await backend.shutdown()

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
        description="Zero-config MCP server for searchable documentation (SQLite default, PostgreSQL optional)",
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
    p_ingest = sub.add_parser("ingest", help="Ingest markdown files")
    p_ingest.add_argument("path", help="File or directory to ingest")
    p_ingest.add_argument("--dry-run", action="store_true", help="Show what would be ingested")

    # search
    p_search = sub.add_parser("search", help="Search documents from the command line")
    p_search.add_argument("query", help="Search query text")
    p_search.add_argument("-n", "--limit", type=int, default=5, help="Max results (default: 5)")
    p_search.add_argument("-c", "--category", default=None, help="Filter by category")
    p_search.add_argument(
        "--embed", action="store_true",
        help="Auto-embed query for hybrid search (requires GNOSIS_MCP_EMBED_PROVIDER)",
    )

    # stats
    sub.add_parser("stats", help="Show documentation statistics")

    # export
    p_export = sub.add_parser("export", help="Export documents as JSON or markdown")
    p_export.add_argument(
        "-f", "--format", choices=["json", "markdown"], default="json", help="Output format (default: json)"
    )
    p_export.add_argument("-c", "--category", default=None, help="Filter by category")

    # embed
    p_embed = sub.add_parser("embed", help="Embed chunks with NULL embeddings")
    p_embed.add_argument(
        "--provider", choices=["openai", "ollama", "custom"], default=None,
        help="Embedding provider (overrides GNOSIS_MCP_EMBED_PROVIDER)",
    )
    p_embed.add_argument("--model", default=None, help="Embedding model name")
    p_embed.add_argument(
        "--batch-size", type=int, default=None, help="Chunks per batch (default: 50)"
    )
    p_embed.add_argument("--dry-run", action="store_true", help="Count NULL embeddings only")

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
        "embed": cmd_embed,
        "stats": cmd_stats,
        "export": cmd_export,
        "check": cmd_check,
    }
    commands[args.command](args)
