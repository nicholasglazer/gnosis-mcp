"""Command-line interface: serve, init-db, ingest, crawl, search, stats, export, check."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter

from gnosis_mcp import __version__

__all__ = ["main"]

log = logging.getLogger("gnosis_mcp")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.server import mcp

    config = GnosisMcpConfig.from_env()

    # --watch implies --ingest with the same path
    ingest_root = args.watch or args.ingest

    if ingest_root:
        from gnosis_mcp.ingest import ingest_path

        async def _ingest() -> None:
            results = await ingest_path(
                config=config,
                root=ingest_root,
            )
            ingested = sum(1 for r in results if r.action == "ingested")
            unchanged = sum(1 for r in results if r.action == "unchanged")
            total = sum(r.chunks for r in results)
            log.info("Ingest: %d new, %d unchanged (%d total chunks)", ingested, unchanged, total)

        asyncio.run(_ingest())

    if args.watch:
        from gnosis_mcp.watch import start_watcher

        start_watcher(args.watch, config, embed=True)

    transport = args.transport or config.transport
    host = getattr(args, "host", None) or config.host
    port = getattr(args, "port", None) or config.port

    # Pass host/port to FastMCP settings for HTTP transports
    if transport in ("sse", "streamable-http"):
        mcp.settings.host = host
        mcp.settings.port = port

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
            await backend.init_schema()
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

            if "sqlite_vec" in health:
                log.info("sqlite-vec: %s", "loaded" if health["sqlite_vec"] else "not available")
                if health.get("vec_table_exists"):
                    log.info("Vec0 table: %d vectors", health.get("vec_count", 0))

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
    """Ingest files into the database."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import ingest_path

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        results = await ingest_path(
            config=config,
            root=args.path,
            dry_run=args.dry_run,
            force=getattr(args, "force", False),
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

        # Embed after ingest if requested
        if getattr(args, "embed", False) and not args.dry_run and total_chunks > 0:
            from gnosis_mcp.embed import embed_pending

            provider = config.embed_provider
            if not provider and _detect_local_provider():
                provider = "local"
                log.info("Auto-detected local embedding provider")

            if not provider:
                log.warning(
                    "Skipping --embed: no provider configured and [embeddings] not installed"
                )
                return

            model = config.embed_model if config.embed_provider else "MongoDB/mdbr-leaf-ir"
            if provider != "local":
                model = config.embed_model

            log.info("Embedding chunks with provider=%s model=%s ...", provider, model)
            embed_result = await embed_pending(
                config=config,
                provider=provider,
                model=model,
                api_key=config.embed_api_key,
                url=config.embed_url,
                batch_size=config.embed_batch_size,
                dim=config.embed_dim,
            )
            log.info(
                "Embedded: %d/%d chunks (%d errors)",
                embed_result.embedded, embed_result.total_null, embed_result.errors,
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
                if not provider and _detect_local_provider():
                    provider = "local"
                if not provider:
                    log.error(
                        "--embed requires GNOSIS_MCP_EMBED_PROVIDER or gnosis-mcp[embeddings]"
                    )
                    return
                from gnosis_mcp.embed import embed_texts

                model = config.embed_model
                if provider == "local" and not config.embed_provider:
                    model = "MongoDB/mdbr-leaf-ir"

                vectors = embed_texts(
                    [args.query],
                    provider=provider,
                    model=model,
                    api_key=config.embed_api_key,
                    url=config.embed_url,
                    dim=config.embed_dim,
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
                highlight = r.get("highlight")
                content = r["content"]
                snippet = content[:preview] + "..." if len(content) > preview else content
                sys.stdout.write(f"\n  {r['file_path']}  (score: {score})\n")
                sys.stdout.write(f"  {r['title']}\n")
                if highlight:
                    sys.stdout.write(f"  {highlight}\n")
                else:
                    sys.stdout.write(f"  {snippet}\n")

            if not results:
                log.info("No results for: %s", args.query)
            else:
                sys.stdout.write(f"\n  {len(results)} result(s)\n")
        finally:
            await backend.shutdown()

    asyncio.run(_run())


def _detect_local_provider() -> bool:
    """Check if the [embeddings] extra is installed."""
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401

        return True
    except ImportError:
        return False


def cmd_embed(args: argparse.Namespace) -> None:
    """Embed chunks with NULL embeddings using a configured provider."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.embed import embed_pending

    config = GnosisMcpConfig.from_env()
    provider = args.provider or config.embed_provider

    # Auto-detect: if no provider set and [embeddings] extra is installed, use local
    if not provider and _detect_local_provider():
        provider = "local"
        log.info("Auto-detected local embedding provider (onnxruntime installed)")

    if not provider:
        log.error(
            "No embedding provider configured. "
            "Set GNOSIS_MCP_EMBED_PROVIDER, use --provider, or install gnosis-mcp[embeddings]."
        )
        sys.exit(1)

    model = args.model or (
        config.embed_model if config.embed_provider else "MongoDB/mdbr-leaf-ir"
    ) if provider == "local" else (args.model or config.embed_model)
    batch_size = args.batch_size or config.embed_batch_size
    api_key = config.embed_api_key
    url = config.embed_url
    dim = config.embed_dim

    async def _run() -> None:
        result = await embed_pending(
            config=config,
            provider=provider,
            model=model,
            api_key=api_key,
            url=url,
            batch_size=batch_size,
            dry_run=args.dry_run,
            dim=dim,
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
            if s.get("embedded_chunks") is not None:
                sys.stdout.write(f"  Embedded:  {s['embedded_chunks']}\n")
            sys.stdout.write(f"  Content:   {_format_bytes(s['content_bytes'])}\n")
            if s.get("sqlite_vec") is not None:
                sys.stdout.write(
                    f"  Vector:    {'sqlite-vec loaded' if s['sqlite_vec'] else 'keyword only'}\n"
                )
            sys.stdout.write("\n")

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
            elif fmt == "csv":
                import csv as csv_mod

                writer = csv_mod.writer(sys.stdout)
                writer.writerow(["file_path", "title", "category", "chunks"])
                for d in docs:
                    chunk_count = d["content"].count("\n\n") + 1 if d["content"] else 0
                    writer.writerow([d["file_path"], d["title"], d["category"], chunk_count])
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


def cmd_crawl(args: argparse.Namespace) -> None:
    """Crawl a documentation website and ingest into the database."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.crawl import CrawlConfig, crawl_url

    config = GnosisMcpConfig.from_env()

    crawl_config = CrawlConfig(
        sitemap=args.sitemap,
        depth=args.depth,
        include=getattr(args, "include", None),
        exclude=getattr(args, "exclude", None),
        dry_run=args.dry_run,
        force=getattr(args, "force", False),
        embed=getattr(args, "embed", False),
        max_urls=getattr(args, "max_urls", 5000),
    )

    async def _run() -> None:
        results = await crawl_url(config, args.url, crawl_config)

        # Print results
        total_chunks = 0
        counts: Counter[str] = Counter()
        for r in results:
            counts[r.action] += 1
            total_chunks += r.chunks
            marker = {
                "crawled": "+", "unchanged": "=", "skipped": "-",
                "error": "!", "blocked": "x", "dry-run": "?",
            }
            sym = marker.get(r.action, " ")
            detail = f"  ({r.detail})" if r.detail else ""
            log.info("[%s] %s  (%d chunks)%s", sym, r.url, r.chunks, detail)

        log.info("")
        log.info(
            "Done: %d crawled, %d unchanged, %d skipped, %d errors, %d blocked (%d total chunks)",
            counts["crawled"],
            counts["unchanged"],
            counts["skipped"],
            counts["error"],
            counts["blocked"],
            total_chunks,
        )

    asyncio.run(_run())


def cmd_diff(args: argparse.Namespace) -> None:
    """Show what would change on re-ingest."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import diff_path

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        result = await diff_path(config, args.path)

        for p in result["new"]:
            log.info("[+] %s  (new)", p)
        for p in result["modified"]:
            log.info("[~] %s  (modified)", p)
        for p in result["deleted"]:
            log.info("[-] %s  (deleted from disk)", p)

        sys.stdout.write(
            f"\n  {len(result['new'])} new, "
            f"{len(result['modified'])} modified, "
            f"{len(result['deleted'])} deleted, "
            f"{len(result['unchanged'])} unchanged\n"
        )

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
        choices=["stdio", "sse", "streamable-http"],
        default=None,
        help="Transport protocol (default: from GNOSIS_MCP_TRANSPORT or stdio)",
    )
    p_serve.add_argument(
        "--host", default=None,
        help="Host to bind HTTP server (default: 127.0.0.1, env: GNOSIS_MCP_HOST)",
    )
    p_serve.add_argument(
        "--port", type=int, default=None,
        help="Port for HTTP server (default: 8000, env: GNOSIS_MCP_PORT)",
    )
    p_serve.add_argument(
        "--ingest",
        metavar="PATH",
        default=None,
        help="Ingest files from PATH before starting the server",
    )
    p_serve.add_argument(
        "--watch",
        metavar="PATH",
        default=None,
        help="Watch PATH for file changes and auto-re-ingest (implies --ingest)",
    )

    # init-db
    p_init = sub.add_parser("init-db", help="Create documentation tables")
    p_init.add_argument("--dry-run", action="store_true", help="Print SQL without executing")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest files (.md, .txt, .ipynb, .toml, .csv, .json)")
    p_ingest.add_argument("path", help="File or directory to ingest")
    p_ingest.add_argument("--dry-run", action="store_true", help="Show what would be ingested")
    p_ingest.add_argument(
        "--force", action="store_true",
        help="Re-ingest all files, ignoring content hash (skip-if-unchanged)",
    )
    p_ingest.add_argument(
        "--embed", action="store_true",
        help="Embed all chunks after ingestion (auto-detects local provider if installed)",
    )

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
        "-f", "--format", choices=["json", "markdown", "csv"], default="json", help="Output format (default: json)"
    )
    p_export.add_argument("-c", "--category", default=None, help="Filter by category")

    # embed
    p_embed = sub.add_parser("embed", help="Embed chunks with NULL embeddings")
    p_embed.add_argument(
        "--provider", choices=["openai", "ollama", "custom", "local"], default=None,
        help="Embedding provider (overrides GNOSIS_MCP_EMBED_PROVIDER)",
    )
    p_embed.add_argument("--model", default=None, help="Embedding model name")
    p_embed.add_argument(
        "--batch-size", type=int, default=None, help="Chunks per batch (default: 50)"
    )
    p_embed.add_argument("--dry-run", action="store_true", help="Count NULL embeddings only")

    # crawl
    p_crawl = sub.add_parser(
        "crawl", help="Crawl a documentation website and ingest pages"
    )
    p_crawl.add_argument("url", help="Base URL to crawl (e.g. https://docs.example.com/)")
    p_crawl.add_argument(
        "--sitemap", action="store_true",
        help="Discover URLs from sitemap.xml instead of link crawling",
    )
    p_crawl.add_argument(
        "--depth", type=int, default=1,
        help="Maximum link-crawl depth (default: 1, ignored with --sitemap)",
    )
    p_crawl.add_argument(
        "--include", default=None,
        help="Only crawl URLs whose path matches this glob (e.g. '/docs/*')",
    )
    p_crawl.add_argument(
        "--exclude", default=None,
        help="Skip URLs whose path matches this glob",
    )
    p_crawl.add_argument("--dry-run", action="store_true", help="Discover URLs only, don't fetch")
    p_crawl.add_argument(
        "--force", action="store_true",
        help="Re-crawl all pages ignoring cache and content hash",
    )
    p_crawl.add_argument(
        "--embed", action="store_true",
        help="Embed all chunks after crawling",
    )
    p_crawl.add_argument(
        "--max-urls", type=int, default=5000,
        help="Maximum number of URLs to crawl (default: 5000)",
    )

    # diff
    p_diff = sub.add_parser("diff", help="Show what would change on re-ingest")
    p_diff.add_argument("path", help="File or directory to compare")

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
        "crawl": cmd_crawl,
        "search": cmd_search,
        "embed": cmd_embed,
        "stats": cmd_stats,
        "export": cmd_export,
        "diff": cmd_diff,
        "check": cmd_check,
    }
    commands[args.command](args)
