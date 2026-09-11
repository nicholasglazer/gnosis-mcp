"""Command-line interface: serve, init-db, ingest, crawl, search, stats, export, check, cleanup."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from gnosis_mcp import __version__, clients

__all__ = ["main"]

log = logging.getLogger("gnosis_mcp")


def _apply_serve_overrides(args: argparse.Namespace) -> None:
    """Push `serve` tuning overrides into the environment before config is built.

    `GnosisMcpConfig.from_env()` is the only construction point for `serve`, and
    the FastMCP lifespan (`db.app_lifespan`) builds its *own* config from the
    environment once the server starts — so a locally patched config object
    (e.g. `dataclasses.replace`) would leave the MCP tools, the REST routes and
    the watcher reading the old values. Setting the env vars keeps a single
    config path, and `GnosisMcpConfig.__post_init__` then validates a bad CLI
    value with the same `GNOSIS_MCP_*` message an env var would produce.
    """
    if args.search_limit_max is not None:
        os.environ["GNOSIS_MCP_SEARCH_LIMIT_MAX"] = str(args.search_limit_max)
    if args.content_preview_chars is not None:
        os.environ["GNOSIS_MCP_CONTENT_PREVIEW_CHARS"] = str(args.content_preview_chars)


def _check_reranker(config) -> None:
    """Complain at startup when reranking is on but its model cannot be fetched.

    Search degrades to unranked results whenever the reranker cannot load. That
    is deliberate — a missing model must not break search — but it made a broken
    `GNOSIS_MCP_RERANK_MODEL` indistinguishable from a slow query: the only
    signal was one "Rerank failed" traceback in the log of the first search.
    Probing here puts the diagnosis where an operator will see it. The probe is a
    HEAD request, skipped entirely when the model is already cached, and never
    fatal: the server still starts and still serves unranked results.
    """
    if not config.rerank_enabled:
        return

    from gnosis_mcp.rerank import DEFAULT_MODEL, check_model_available

    try:
        available, detail = check_model_available(config.rerank_model)
    except Exception as exc:  # a probe must never stop `serve`
        log.debug("reranker probe failed: %s", exc)
        return

    if available:
        log.info("Reranker model %s is available (%s)", config.rerank_model, detail)
        return

    log.error(
        "Reranking is enabled but its model '%s' cannot be fetched (%s). Searches will "
        "return unranked results. Set GNOSIS_MCP_RERANK_MODEL to a fetchable cross-encoder "
        "(e.g. '%s'), or disable reranking with GNOSIS_MCP_RERANK_ENABLED=false.",
        config.rerank_model,
        detail,
        DEFAULT_MODEL,
    )


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.server import mcp

    # Before any config is built — `from_env()` below and the lifespan's own
    # `from_env()` inside the server process must both see the CLI values.
    _apply_serve_overrides(args)

    config = GnosisMcpConfig.from_env()
    _check_reranker(config)

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

    rest_enabled = args.rest if args.rest else config.rest

    if rest_enabled and transport == "stdio":
        log.warning(
            "--rest flag ignored: REST API requires an HTTP transport (use --transport streamable-http or sse)"
        )

    # SECURITY: warn loudly if the REST API would be exposed unauthenticated on a
    # non-loopback interface. The Docker image binds 0.0.0.0 with --rest by
    # default; without GNOSIS_MCP_API_KEY the entire read API plus POST /v1/embed
    # (arbitrary HuggingFace model download + ONNX compute) is open to anyone who
    # can reach the port. Bind to 127.0.0.1 or set GNOSIS_MCP_API_KEY in prod.
    if rest_enabled and transport in ("sse", "streamable-http"):
        if host not in ("127.0.0.1", "::1", "localhost", "") and not config.api_key:
            log.warning(
                "SECURITY: REST API is UNAUTHENTICATED and bound to a non-loopback host (%s). "
                "Anyone who can reach this port has full read access plus /v1/embed "
                "(arbitrary model download + compute). Set GNOSIS_MCP_API_KEY to require a "
                "Bearer token, or bind --host 127.0.0.1.",
                host,
            )

    if rest_enabled and transport in ("sse", "streamable-http"):
        import uvicorn
        from gnosis_mcp.rest import create_combined_app

        app = create_combined_app(mcp, transport, config)
        log.info("REST API enabled at /api/* and /health")
        uvicorn.run(app, host=host, port=int(port))
    elif transport in ("sse", "streamable-http"):
        # Always mount /health even without --rest (operational necessity)
        import uvicorn
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route

        async def _health(request: Request) -> JSONResponse:
            return JSONResponse(
                {
                    "status": "ok",
                    "version": __version__,
                    "transport": transport,
                }
            )

        if transport == "sse":
            mcp_app = mcp.sse_app()
        else:
            mcp_app = mcp.streamable_http_app()

        app = Starlette(
            routes=[
                Route("/health", _health, methods=["GET"]),
                Mount("/", app=mcp_app),
            ],
            lifespan=mcp_app.router.lifespan_context,
        )
        log.info("/health endpoint available (use --rest for full REST API)")
        uvicorn.run(app, host=host, port=int(port))
    else:
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


def _is_missing_schema_error(exc: BaseException) -> bool:
    """True when `exc` means "the schema was never created".

    SQLite raises ``sqlite3.OperationalError: no such table: documentation_chunks_fts``
    and PostgreSQL raises asyncpg's ``UndefinedTableError: relation ... does not
    exist``. ``no such column`` is the same class of problem for a database created
    by an older version. All of them are fixed by the same command.
    """
    if type(exc).__name__ in ("UndefinedTableError", "UndefinedColumnError"):
        return True
    message = str(exc).lower()
    return "no such table" in message or "no such column" in message


def _require_schema(command):
    """Turn "schema was never initialized" into guidance instead of a traceback.

    `search`, `stats`, `export`, `embed`, `prune`, `diff`, `cleanup` and
    `fix-link-types` all assume `init-db` (or `ingest`) has run at least once. On a
    fresh database they used to surface aiosqlite's raw
    ``sqlite3.OperationalError: no such table: ...`` with a full traceback and no
    hint, while `check` and the MCP tools already told the user to run
    `gnosis-mcp init-db`. Commands that create the schema themselves
    (`ingest`, `crawl`, `ingest-git`) are deliberately not wrapped.
    """

    @functools.wraps(command)
    def wrapper(args: argparse.Namespace) -> int | None:
        try:
            return command(args)
        except Exception as exc:
            if not _is_missing_schema_error(exc):
                raise
            log.error(
                "Database schema is not initialized: %s. Run `gnosis-mcp init-db`, "
                "then `gnosis-mcp ingest <path>` to index your docs (exit 1).",
                exc,
            )
            return 1

    return wrapper


def _missing_schema_parts(health: dict) -> list[str]:
    """Schema pieces the server needs that `check_health()` reports as absent.

    Only keys the backend explicitly reports as `False` count — PostgreSQL has no
    FTS5 index, and a backend that does not report a key at all is not making a
    claim about it. `search_access_log` is deliberately absent from this list:
    access logging is fire-and-forget, so a missing table degrades `get_context`
    without breaking the server.
    """
    missing: list[str] = []
    if health.get("chunks_table_exists") is False:
        missing.append("chunks table")
    if health.get("fts_table_exists") is False:
        missing.append("FTS5 index")
    if health.get("links_table_exists") is False:
        missing.append("links table")
    return missing


async def _collect_health(config) -> tuple[dict | None, str | None]:
    """Start the backend, read health, and always shut it down.

    Returns `(health, error)` with exactly one of them None. `check` and
    `doctor` ask different questions of the same probe, and the shutdown has to
    happen on every path — including the failure paths, where it is easiest to
    forget.
    """
    from gnosis_mcp.backend import create_backend

    backend = create_backend(config)
    try:
        await backend.startup()
    except Exception as exc:
        return None, f"Cannot start the {config.backend} backend: {exc}"
    try:
        try:
            return await backend.check_health(), None
        except Exception as exc:
            return None, f"Health check failed: {exc}"
    finally:
        await backend.shutdown()


def _log_health(health: dict) -> None:
    """The per-field health block shared by `check` and `doctor`."""
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


def cmd_check(args: argparse.Namespace) -> int:
    """Verify database connection and schema.

    Returns the exit status `main()` turns into the process status: 0 when the
    backend started and the tables the server needs are present, 1 when the
    backend cannot be reached or the schema was never initialized. That makes
    `gnosis-mcp check` usable as a gate in setup scripts, installers, and CI.
    """
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> int:
        health, error = await _collect_health(config)
        if health is None:
            log.error("%s", error)
            log.error("Result: unhealthy (exit 1).")
            return 1

        _log_health(health)

        missing = _missing_schema_parts(health)
        if missing:
            log.info("Run `gnosis-mcp init-db` to create tables.")
            log.error(
                "Result: unhealthy — schema not initialized; missing: %s (exit 1).",
                ", ".join(missing),
            )
            return 1

        log.info("All checks passed.")
        log.info("Result: healthy (exit 0).")
        return 0

    return asyncio.run(_run())


def cmd_setup(args: argparse.Namespace) -> int:
    """Wire the server into the MCP clients on this machine.

    Installing the package is half an installation. This is the other half, and
    it exists because the honest previous answer — "add this JSON to your client
    config" — is exactly where users stop: the snippet names a binary, and the
    path that is correct on the author's machine is wrong on theirs. Everything
    below is derived from the interpreter running this command.

    Prints by default so it is safe to run on someone else's machine, and only
    writes with ``--write``. Exits 1 when a requested client could not be wired,
    so an installer or an agent can gate on it.
    """
    from gnosis_mcp import clients

    if args.list_clients:
        sys.stdout.write("\n  Supported clients\n  " + "=" * 52 + "\n")
        for client in clients.CLIENTS:
            mark = "verified" if client.verified else "        "
            sys.stdout.write(f"    {client.name:<14}{mark}  {client.label}\n")
        sys.stdout.write(
            "\n  `setup --write` uses each client's own `mcp add` command when it is\n"
            "  installed, and otherwise edits its config file directly.\n\n"
        )
        return 0

    env = clients.detect_env(dsh_profile=args.dsh_profile)
    requested = args.client or clients.detected_clients(env, use_cli=not args.no_cli)
    if not requested:
        requested = ["generic"]

    reports: list[dict] = []
    failures: list[str] = []
    for name in requested:
        try:
            report = clients.configure(name, write=args.write, env=env, use_cli=not args.no_cli)
        except ValueError as exc:
            reports.append({"client": name, "error": str(exc)})
            failures.append(f"{name}: {exc}")
            continue
        reports.append(report)
        if args.write and not report.get("wrote"):
            failures.append(f"{name}: {report.get('warning') or 'nothing was written'}")

    if args.json:
        sys.stdout.write(json.dumps({"written": args.write, "clients": reports}, indent=2) + "\n")
        return 1 if failures else 0

    command = clients.resolve_command()
    sys.stdout.write("\n  gnosis-mcp setup\n  " + "=" * 52 + "\n")
    sys.stdout.write(f"  server command   {' '.join(command)}\n")
    sys.stdout.write(
        f"  mode             {'writing config' if args.write else 'preview (add --write)'}\n"
    )

    for report in reports:
        sys.stdout.write("\n")
        if "error" in report:
            sys.stdout.write(f"  {report['client']}  — {report['error']}\n")
            continue
        sys.stdout.write(f"  {report['client']}  {report['label']}\n")
        if report.get("path"):
            sys.stdout.write(f"    config    {report['path']}\n")
        if report.get("wrote"):
            sys.stdout.write(f"    wrote     {report.get('action', 'ok')}\n")
        if report.get("rules_path"):
            sys.stdout.write(
                f"    rule      {report['rules_path']} ({report.get('rules_action')})\n"
            )
        cli = report.get("cli")
        if isinstance(cli, dict) and cli.get("argv"):
            sys.stdout.write(f"    via cli   {' '.join(cli['argv'])}\n")
        if not report.get("wrote"):
            sys.stdout.write("    snippet:\n")
            for line in str(report.get("snippet", "")).splitlines():
                sys.stdout.write(f"      {line}\n")
        if report.get("warning"):
            sys.stdout.write(f"    warning   {report['warning']}\n")
        if report.get("note"):
            sys.stdout.write(f"    note      {report['note']}\n")

    sys.stdout.write("\n")
    if failures:
        for failure in failures:
            sys.stdout.write(f"  failed: {failure}\n")
        sys.stdout.write("\n  Result: incomplete (exit 1).\n\n")
        return 1
    if args.write:
        sys.stdout.write("  Result: wired. Run `gnosis-mcp doctor` to confirm it gets called.\n\n")
    else:
        sys.stdout.write("  Re-run with --write to apply. Nothing was modified.\n\n")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Answer "is it installed, and is it actually being used?".

    `check` answers the first half: the database starts and the schema is there.
    That is necessary and not sufficient. Two things still fail silently after
    `check` passes — a client wired to a binary path that no longer exists, and
    a correctly wired client whose agent never calls the server — and both look
    identical from the outside: no results, no error, no log line.

    So this adds the two halves `check` cannot see: what each client's config
    currently says, and who the access log says has actually called. The second
    is the only non-speculative answer to "will users use it", because it is
    evidence rather than intent.
    """
    from gnosis_mcp import clients
    from gnosis_mcp.config import GnosisMcpConfig

    env = clients.detect_env(dsh_profile=args.dsh_profile)
    config = GnosisMcpConfig.from_env()
    command = clients.resolve_command()

    async def _probe() -> dict:
        from gnosis_mcp.backend import create_backend

        backend = create_backend(config)
        try:
            await backend.startup()
        except Exception as exc:
            return {"error": f"Cannot start the {config.backend} backend: {exc}"}
        try:
            out: dict = {"health": await backend.check_health()}
        except Exception as exc:
            return {"error": f"Health check failed: {exc}"}
        try:
            # A schema that predates the `client` column returns [] rather than
            # raising, so this is the only place a usage query can legitimately
            # fail — and a diagnostic must not die on its least important part.
            out["usage"] = await backend.client_usage(days=args.days)
            out["savings"] = await backend.savings_report(days=args.days)
        except Exception as exc:
            out["usage_error"] = str(exc)
        finally:
            await backend.shutdown()
        return out

    probe = asyncio.run(_probe())
    wiring = clients.scan(env=env)
    verified = (
        {"checked": False, "detail": "skipped"} if args.no_verify else clients.verify_dsh(env)
    )

    wired = [row for row in wiring if row.get("configured")]
    usage = probe.get("usage") or []
    health = probe.get("health")

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "server": {"command": command, "version": __version__},
                    "database": probe,
                    "wiring": wiring,
                    "composition": verified,
                    "usage": usage,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
        return 0 if (health is not None and not probe.get("error")) else 1

    sys.stdout.write("\n  gnosis-mcp doctor\n  " + "=" * 52 + "\n")
    sys.stdout.write(f"  version          {__version__}\n")
    sys.stdout.write(f"  server command   {' '.join(command)}\n")
    executable = Path(command[0])
    sys.stdout.write(
        f"  executable       {executable} ({'found' if executable.exists() else 'MISSING'})\n"
    )

    if probe.get("error"):
        sys.stdout.write(f"\n  Database\n    {probe['error']}\n")
    elif health is not None:
        sys.stdout.write("\n  Database\n")
        for key, label in (
            ("backend", "backend"),
            ("path", "path"),
            ("chunks_count", "chunks"),
            ("links_count", "links"),
            ("vec_count", "vectors"),
        ):
            if health.get(key) is not None:
                sys.stdout.write(f"    {label:<16} {health[key]}\n")
        if health.get("fts_table_exists") is not None:
            sys.stdout.write(
                f"    {'keyword index':<16} {'ready' if health['fts_table_exists'] else 'MISSING'}\n"
            )

    sys.stdout.write("\n  Clients\n")
    if not wiring:
        sys.stdout.write("    (no client configs located on this machine)\n")
    for row in wiring:
        if "error" in row:
            sys.stdout.write(f"    {row['client']:<14} ?  {row['error']}\n")
            continue
        state = (
            "wired" if row.get("configured") else ("present" if row.get("exists") else "absent")
        )
        sys.stdout.write(f"    {row['client']:<14} {state:<8} {row['path']}\n")

    if verified.get("checked"):
        argv = verified.get("argv") or []
        profile = argv[argv.index("--profile") + 1] if "--profile" in argv else "?"
        sys.stdout.write("\n  Harness composition\n")
        sys.stdout.write(f"    {profile} profile: {verified['detail']}\n")

    window = f"last {args.days} day{'s' if args.days != 1 else ''}"
    sys.stdout.write(f"\n  Usage — {window}\n")
    if probe.get("usage_error"):
        sys.stdout.write(f"    usage query failed: {probe['usage_error']}\n")
    elif not usage:
        sys.stdout.write("    no calls recorded.\n")
    else:
        for row in usage:
            who = row["client"] or "(no client identity — pre-0.16 rows)"
            sys.stdout.write(
                f"    {who:<34}{row['calls']:>7,} calls   last {row.get('last_accessed') or '—'}\n"
            )
        savings = probe.get("savings") or {}
        if savings.get("calls"):
            sys.stdout.write(f"    {'':<34}{savings.get('tokens_saved', 0):>7,} tokens saved\n")

    problems: list[str] = []
    if probe.get("error"):
        problems.append(probe["error"])
    if health is not None:
        missing_parts = _missing_schema_parts(health)
        if missing_parts:
            problems.append(
                f"schema not initialized (missing: {', '.join(missing_parts)}) — "
                "run `gnosis-mcp init-db`"
            )
    if not wired:
        problems.append("no client is wired up — run `gnosis-mcp setup --write`")
    if verified.get("checked") and not verified.get("ok"):
        problems.append(f"the harness rejects the composed profile: {verified['detail']}")

    sys.stdout.write("\n")
    if problems:
        for problem in problems:
            sys.stdout.write(f"  problem: {problem}\n")
        sys.stdout.write("\n  Result: needs attention (exit 1).\n\n")
        return 1

    # Wired but never called is the failure this command exists to make visible,
    # and it is a warning rather than a failure: a machine that installed gnosis
    # five minutes ago is in exactly this state and is fine. `--strict` turns it
    # into an exit code for a CI job that wants to assert real usage.
    if not usage:
        sys.stdout.write(
            "  warning: a client is wired but no call has ever been logged.\n"
            "           Connect to gnosis from that client once, then re-run.\n"
        )
        if args.strict:
            sys.stdout.write("\n  Result: not used (exit 1, --strict).\n\n")
            return 1
    else:
        sys.stdout.write("  A client has called this server — the wiring is live.\n")

    sys.stdout.write("\n  Result: healthy (exit 0).\n\n")
    return 0


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest files into the database."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import ingest_path, prune_stale

    config = GnosisMcpConfig.from_env()

    async def _maybe_wipe() -> None:
        if not getattr(args, "wipe", False):
            return
        backend = create_backend(config)
        await backend.startup()
        try:
            docs = await backend.list_docs()
            for d in docs:
                try:
                    await backend.delete_doc(d["file_path"])
                except Exception:
                    log.exception("wipe failed for %s", d["file_path"])
            log.info("Wiped %d document(s) before re-ingest", len(docs))
        finally:
            await backend.shutdown()

    async def _maybe_prune() -> None:
        if not getattr(args, "prune", False):
            return
        backend = create_backend(config)
        await backend.startup()
        try:
            report = await prune_stale(
                backend,
                args.path,
                dry_run=getattr(args, "dry_run", False),
                include_crawled=getattr(args, "include_crawled", False),
                include_generated=getattr(args, "include_generated", False),
                config=config,
            )
            if report["pruned"]:
                verb = "Would prune" if report["dry_run"] else "Pruned"
                log.info("%s %d stale document(s):", verb, len(report["pruned"]))
                for p in report["pruned"][:50]:
                    log.info("  - %s", p)
                if len(report["pruned"]) > 50:
                    log.info("  ... and %d more", len(report["pruned"]) - 50)
            else:
                log.info(
                    "No stale documents to prune (%d in scope for this root, %d in DB — "
                    "the rest belong to other ingesters).",
                    report["in_scope"],
                    report["kept"],
                )
        finally:
            await backend.shutdown()

    async def _run() -> None:
        await _maybe_wipe()
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
            marker = {
                "ingested": "+",
                "unchanged": "=",
                "skipped": "-",
                "error": "!",
                "dry-run": "?",
            }
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
                embed_result.embedded,
                embed_result.total_null,
                embed_result.errors,
            )
            if embed_result.total_failure:
                log.error(
                    "No chunk could be embedded (%d errors). Documents are ingested "
                    "and searchable by text, but semantic search is unavailable until "
                    "this is re-run — is the embedding provider reachable?",
                    embed_result.errors,
                )
                return True
        return False

    embed_failed = asyncio.run(_run())
    # Prune after ingest so fresh chunks are kept and missing-file chunks go away.
    asyncio.run(_maybe_prune())
    # Exit non-zero only on total failure: callers that wrap this command (git
    # hooks, setup scripts, CI) see the exit code, not the log, so an ingest that
    # embedded nothing must not look like a success.
    if embed_failed:
        sys.exit(1)


@_require_schema
def cmd_prune(args: argparse.Namespace) -> None:
    """Remove chunks from the DB whose source file no longer exists on disk."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import prune_stale

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            report = await prune_stale(
                backend,
                args.path,
                dry_run=args.dry_run,
                include_crawled=args.include_crawled,
                include_generated=args.include_generated,
                config=config,
            )
            if report["pruned"]:
                verb = "Would prune" if report["dry_run"] else "Pruned"
                log.info("%s %d stale document(s):", verb, len(report["pruned"]))
                for p in report["pruned"][:50]:
                    log.info("  - %s", p)
                if len(report["pruned"]) > 50:
                    log.info("  ... and %d more", len(report["pruned"]) - 50)
            else:
                log.info(
                    "No stale documents to prune (%d in scope for this root, %d in DB — "
                    "the rest belong to other ingesters).",
                    report["in_scope"],
                    report["kept"],
                )
        finally:
            await backend.shutdown()

    asyncio.run(_run())


@_require_schema
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
                try:
                    stats = await backend.get_stats()
                    chunk_count = stats.get("chunk_count", 0) if isinstance(stats, dict) else 0
                except Exception:
                    chunk_count = 0
                if chunk_count == 0:
                    log.info("No documents indexed. Run: gnosis-mcp ingest <path>")
                else:
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


@_require_schema
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

    model = (
        args.model or (config.embed_model if config.embed_provider else "MongoDB/mdbr-leaf-ir")
        if provider == "local"
        else (args.model or config.embed_model)
    )
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
            if result.total_failure:
                return True
        return False

    if asyncio.run(_run()):
        # Same reasoning as `ingest --embed`: embedding nothing is not a success.
        sys.exit(1)


@_require_schema
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


@_require_schema
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
                # `export_docs` reassembles the chunk bodies and drops the row
                # count, so the true count comes from `list_docs` (COUNT(*) per
                # file_path). Counting blank lines in the reassembled content —
                # what this used to do — reported *paragraphs*, not chunks: a
                # document with 2 chunks but 6 paragraphs claimed 6 chunks.
                chunk_counts = {d["file_path"]: d["chunks"] for d in await backend.list_docs()}
                for d in docs:
                    writer.writerow(
                        [
                            d["file_path"],
                            d["title"],
                            d["category"],
                            chunk_counts.get(d["file_path"], 0),
                        ]
                    )
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
                "crawled": "+",
                "unchanged": "=",
                "skipped": "-",
                "error": "!",
                "blocked": "x",
                "dry-run": "?",
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


def cmd_ingest_git(args: argparse.Namespace) -> None:
    """Ingest git commit history into the database."""
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.parsers.git_history import GitIngestConfig, ingest_git

    config = GnosisMcpConfig.from_env()

    git_config = GitIngestConfig(
        since=args.since,
        until=getattr(args, "until", None),
        author=getattr(args, "author", None),
        max_commits=args.max_commits,
        include=getattr(args, "include", None),
        exclude=getattr(args, "exclude", None),
        embed=getattr(args, "embed", False),
        dry_run=args.dry_run,
        merge_commits=getattr(args, "merges", False),
        force=getattr(args, "force", False),
    )

    async def _run() -> None:
        results = await ingest_git(config, args.repo, git_config)

        total_chunks = 0
        counts: Counter[str] = Counter()
        for r in results:
            counts[r.action] += 1
            total_chunks += r.chunks
            marker = {
                "ingested": "+",
                "unchanged": "=",
                "skipped": "-",
                "error": "!",
                "dry-run": "?",
            }
            sym = marker.get(r.action, " ")
            detail = f"  ({r.detail})" if r.detail else ""
            log.info(
                "[%s] %s  (%d commits, %d chunks)%s",
                sym,
                r.path,
                r.commits,
                r.chunks,
                detail,
            )

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


@_require_schema
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


@_require_schema
def cmd_cleanup(args: argparse.Namespace) -> None:
    """Purge old access log entries."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            deleted = await backend.purge_access_log(args.days)
            log.info("Purged %d access log entries older than %d days", deleted, args.days)
        finally:
            await backend.shutdown()

    asyncio.run(_run())


def cmd_savings(args: argparse.Namespace) -> None:
    """Report estimated token savings from logged tool calls.

    For every logged call we store `tokens_returned` (what the caller got)
    and `tokens_baseline` (what a naive full-doc Read would have cost).
    Summing `baseline - returned` across rows approximates the cumulative
    savings. Estimator uses 4 chars/token — close enough for relative numbers,
    off by ~15 % vs the caller's real tokeniser.
    """
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            report = await backend.savings_report(days=args.days)
        finally:
            await backend.shutdown()

        if args.json:
            sys.stdout.write(json.dumps(report, indent=2))
            sys.stdout.write("\n")
            return

        window = f"last {args.days} day{'s' if args.days != 1 else ''}"
        sys.stdout.write(f"\n  Retrieval savings — {window}\n")
        sys.stdout.write("  " + "=" * 48 + "\n")
        sys.stdout.write(f"  Tool calls:       {report['calls']:>10,}\n")
        sys.stdout.write(f"  Tokens returned:  {report['tokens_returned']:>10,}\n")
        sys.stdout.write(f"  Tokens baseline:  {report['tokens_baseline']:>10,}\n")
        sys.stdout.write(f"  Tokens saved:     {report['tokens_saved']:>10,}\n")
        if report["tokens_baseline"] > 0:
            ratio = report["tokens_baseline"] / max(1, report["tokens_returned"])
            sys.stdout.write(f"  Ratio:            {ratio:>10.1f}×\n")
        sys.stdout.write("  " + "=" * 48 + "\n")
        if report["by_tool"]:
            sys.stdout.write("\n  By tool:\n")
            for t, stats in report["by_tool"].items():
                sys.stdout.write(
                    f"    {t:<22}{stats['calls']:>6,} calls  saved {stats['tokens_saved']:>10,}\n"
                )
        sys.stdout.write("\n")
        if report["calls"] == 0:
            sys.stdout.write(
                "  (no logged calls in window — is GNOSIS_MCP_ACCESS_LOG enabled?)\n\n"
            )

    asyncio.run(_run())


def cmd_eval(args: argparse.Namespace) -> None:
    """Run the bundled retrieval-quality eval harness and print metrics.

    Useful as a one-liner answer to "where are the numbers?" — measures
    Precision@K, MRR, and Hit Rate@K against query/expected-path cases.
    """
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    # Import the fixtures/helpers from the eval harness without requiring pytest.
    tests_dir = _Path(__file__).resolve().parents[2] / "tests"
    if not tests_dir.exists():  # installed package; user needs the repo layout
        log.error(
            "`gnosis-mcp eval` requires the repository checkout with tests/ present. "
            "Install from source: git clone && pip install -e ."
        )
        sys.exit(1)

    sys.path.insert(0, str(tests_dir))
    from eval.test_search_quality import (  # type: ignore
        K,
        SAMPLE_DOCS,
        SAMPLE_GIT_HISTORY_DOCS,
        _load_cases,
        _score_query,
        EvalSummary,
    )

    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.ingest import chunk_by_headings
    from gnosis_mcp.sqlite_backend import SqliteBackend

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = GnosisMcpConfig(database_url=str(_Path(tmp) / "eval.db"), backend="sqlite")
            backend = SqliteBackend(cfg)
            await backend.startup()
            await backend.init_schema()
            for doc in SAMPLE_DOCS + SAMPLE_GIT_HISTORY_DOCS:
                chunks = chunk_by_headings(
                    doc["content"], doc["path"], max_chunk_size=cfg.chunk_size
                )
                await backend.upsert_doc(
                    doc["path"],
                    [c["content"] for c in chunks],
                    title=doc["title"],
                    category=doc["category"],
                )

            cases = _load_cases()
            summary = EvalSummary()
            for case in cases:
                results = await backend.search(
                    case["query"], category=case.get("category"), limit=K
                )
                paths = [r["file_path"] for r in results]
                summary.results.append(
                    _score_query(
                        query=case["query"],
                        expected_paths=case["expected_paths"],
                        returned_paths=paths,
                        description=case.get("description", ""),
                    )
                )
            await backend.shutdown()

        out = {
            "cases": len(summary.results),
            "hit_rate_at_k": round(summary.hit_rate, 3),
            "mrr": round(summary.mrr, 3),
            "mean_precision_at_k": round(summary.mean_precision, 3),
            "k": K,
        }

        if args.json:
            sys.stdout.write(_json.dumps(out, indent=2) + "\n")
            return

        sys.stdout.write(f"\nRetrieval quality — {out['cases']} cases, K={K}\n")
        sys.stdout.write("=" * 48 + "\n")
        for r in summary.results:
            status = "PASS" if r.hit else "MISS"
            sys.stdout.write(
                f"  [{status}] P@{K}={r.precision_at_k:.2f} RR={r.reciprocal_rank:.2f} "
                f"{r.query!r}\n"
            )
        sys.stdout.write("=" * 48 + "\n")
        sys.stdout.write(f"  Hit Rate@{K}:       {out['hit_rate_at_k']:.3f}\n")
        sys.stdout.write(f"  MRR:                {out['mrr']:.3f}\n")
        sys.stdout.write(f"  Mean Precision@{K}: {out['mean_precision_at_k']:.3f}\n")
        sys.stdout.write("=" * 48 + "\n")

    asyncio.run(_run())


@_require_schema
def cmd_fix_link_types(args: argparse.Namespace) -> None:
    """Migrate git-history links from 'relates_to' to proper types.

    `documentation_links` is UNIQUE on (source_path, target_path, relation_type)
    in both backends, and the ingest path already writes the *typed* rows. So on
    the exact database this migration exists for — one carrying both a legacy
    `relates_to` row and its typed twin — the UPDATE collided with the existing
    row and raised `IntegrityError`, aborting the migration before the second
    statement ran. Where the typed row is already there the legacy row is a
    redundant duplicate, so it is deleted rather than rewritten.
    """
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    config = GnosisMcpConfig.from_env()

    # Applied before either UPDATE, against the backend's own links table name.
    template = (
        "DELETE FROM {lt} WHERE relation_type = 'relates_to' "
        "  AND source_path LIKE 'git-history/%' AND {scope} "
        "  AND EXISTS (SELECT 1 FROM {lt} AS typed "
        "               WHERE typed.source_path = {lt}.source_path "
        "                 AND typed.target_path = {lt}.target_path "
        "                 AND typed.relation_type = '{typed}')"
    )

    def dedupe_sql(lt: str) -> tuple[str, str]:
        return (
            template.format(
                lt=lt, scope="target_path LIKE 'git-history/%'", typed="git_co_change"
            ),
            template.format(lt=lt, scope="target_path NOT LIKE 'git-history/%'", typed="git_ref"),
        )

    async def _run() -> None:
        backend = create_backend(config)
        await backend.startup()
        try:
            if config.backend == "sqlite":
                db = backend._db  # noqa: SLF001
                for stmt in dedupe_sql("documentation_links"):
                    await db.execute(stmt)
                cursor = await db.execute(
                    "UPDATE documentation_links SET relation_type = 'git_co_change' "
                    "WHERE source_path LIKE 'git-history/%' AND target_path LIKE 'git-history/%' "
                    "AND relation_type = 'relates_to'"
                )
                co_change_count = cursor.rowcount
                cursor = await db.execute(
                    "UPDATE documentation_links SET relation_type = 'git_ref' "
                    "WHERE source_path LIKE 'git-history/%' AND target_path NOT LIKE 'git-history/%' "
                    "AND relation_type = 'relates_to'"
                )
                ref_count = cursor.rowcount
                await db.commit()
            else:
                async with await backend._acquire() as conn:  # noqa: SLF001
                    cfg_b = backend._cfg  # noqa: SLF001
                    lt = cfg_b.qualified_links_table
                    for stmt in dedupe_sql(lt):
                        await conn.execute(stmt)
                    status1 = await conn.execute(
                        f"UPDATE {lt} SET relation_type = 'git_co_change' "
                        f"WHERE source_path LIKE 'git-history/%' AND target_path LIKE 'git-history/%' "
                        f"AND relation_type = 'relates_to'"
                    )
                    co_change_count = int(status1.split()[-1]) if status1 else 0
                    status2 = await conn.execute(
                        f"UPDATE {lt} SET relation_type = 'git_ref' "
                        f"WHERE source_path LIKE 'git-history/%' AND target_path NOT LIKE 'git-history/%' "
                        f"AND relation_type = 'relates_to'"
                    )
                    ref_count = int(status2.split()[-1]) if status2 else 0

            log.info("Migrated %d links to 'git_co_change'", co_change_count)
            log.info("Migrated %d links to 'git_ref'", ref_count)
            log.info("Total: %d links updated", co_change_count + ref_count)
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
    parser.add_argument("-V", "--version", action="version", version=f"gnosis-mcp {__version__}")
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
        "--host",
        default=None,
        help="Host to bind HTTP server (default: 127.0.0.1, env: GNOSIS_MCP_HOST)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=None,
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
    p_serve.add_argument(
        "--rest",
        action="store_true",
        default=False,
        help="Enable REST API endpoints alongside MCP (env: GNOSIS_MCP_REST)",
    )
    p_serve.add_argument(
        "--search-limit-max",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Cap on the result limit MCP clients may request "
            "(default: 20, env: GNOSIS_MCP_SEARCH_LIMIT_MAX)"
        ),
    )
    p_serve.add_argument(
        "--content-preview-chars",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Snippet length in characters for tool output "
            "(default: 200, env: GNOSIS_MCP_CONTENT_PREVIEW_CHARS)"
        ),
    )

    # init-db
    p_init = sub.add_parser("init-db", help="Create documentation tables")
    p_init.add_argument("--dry-run", action="store_true", help="Print SQL without executing")

    # ingest
    p_ingest = sub.add_parser(
        "ingest", help="Ingest files (.md, .txt, .ipynb, .toml, .csv, .json)"
    )
    p_ingest.add_argument("path", help="File or directory to ingest")
    p_ingest.add_argument("--dry-run", action="store_true", help="Show what would be ingested")
    p_ingest.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest all files, ignoring content hash (skip-if-unchanged)",
    )
    p_ingest.add_argument(
        "--embed",
        action="store_true",
        help="Embed all chunks after ingestion (auto-detects local provider if installed)",
    )
    p_ingest.add_argument(
        "--prune",
        action="store_true",
        help="After ingest, delete chunks whose source file no longer exists on disk",
    )
    p_ingest.add_argument(
        "--wipe",
        action="store_true",
        help="Delete ALL documents before re-ingesting (nuclear option — full reset)",
    )
    p_ingest.add_argument(
        "--include-crawled",
        action="store_true",
        help="When pruning, also consider crawled URLs (default: leave them alone)",
    )
    p_ingest.add_argument(
        "--include-generated",
        action="store_true",
        help=(
            "When pruning, also consider generated documents such as git history "
            "(default: leave them alone — they have no file on disk)"
        ),
    )

    # prune
    p_prune = sub.add_parser(
        "prune",
        help="Delete DB chunks whose source file no longer exists on disk",
    )
    p_prune.add_argument("path", help="Directory (or file) whose corpus to prune")
    p_prune.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    p_prune.add_argument(
        "--include-crawled",
        action="store_true",
        help="Also prune crawled URLs (default: leave them alone)",
    )
    p_prune.add_argument(
        "--include-generated",
        action="store_true",
        help=(
            "Also prune generated documents such as git history (default: leave "
            "them alone — they have no file on disk)"
        ),
    )

    # search
    p_search = sub.add_parser("search", help="Search documents from the command line")
    p_search.add_argument("query", help="Search query text")
    p_search.add_argument("-n", "--limit", type=int, default=5, help="Max results (default: 5)")
    p_search.add_argument("-c", "--category", default=None, help="Filter by category")
    p_search.add_argument(
        "--embed",
        action="store_true",
        help="Auto-embed query for hybrid search (requires GNOSIS_MCP_EMBED_PROVIDER)",
    )

    # stats
    sub.add_parser("stats", help="Show documentation statistics")

    # export
    p_export = sub.add_parser("export", help="Export documents as JSON or markdown")
    p_export.add_argument(
        "-f",
        "--format",
        choices=["json", "markdown", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    p_export.add_argument("-c", "--category", default=None, help="Filter by category")

    # embed
    p_embed = sub.add_parser("embed", help="Embed chunks with NULL embeddings")
    p_embed.add_argument(
        "--provider",
        choices=["openai", "ollama", "custom", "local"],
        default=None,
        help="Embedding provider (overrides GNOSIS_MCP_EMBED_PROVIDER)",
    )
    p_embed.add_argument("--model", default=None, help="Embedding model name")
    p_embed.add_argument(
        "--batch-size", type=int, default=None, help="Chunks per batch (default: 50)"
    )
    p_embed.add_argument("--dry-run", action="store_true", help="Count NULL embeddings only")

    # crawl
    p_crawl = sub.add_parser("crawl", help="Crawl a documentation website and ingest pages")
    p_crawl.add_argument("url", help="Base URL to crawl (e.g. https://docs.example.com/)")
    p_crawl.add_argument(
        "--sitemap",
        action="store_true",
        help="Discover URLs from sitemap.xml instead of link crawling",
    )
    p_crawl.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Maximum link-crawl depth (default: 1, ignored with --sitemap)",
    )
    p_crawl.add_argument(
        "--include",
        default=None,
        help="Only crawl URLs whose path matches this glob (e.g. '/docs/*')",
    )
    p_crawl.add_argument(
        "--exclude",
        default=None,
        help="Skip URLs whose path matches this glob",
    )
    p_crawl.add_argument("--dry-run", action="store_true", help="Discover URLs only, don't fetch")
    p_crawl.add_argument(
        "--force",
        action="store_true",
        help="Re-crawl all pages ignoring cache and content hash",
    )
    p_crawl.add_argument(
        "--embed",
        action="store_true",
        help="Embed all chunks after crawling",
    )
    p_crawl.add_argument(
        "--max-urls",
        type=int,
        default=5000,
        help="Maximum number of URLs to crawl (default: 5000)",
    )

    # ingest-git
    p_igit = sub.add_parser("ingest-git", help="Ingest git commit history as searchable documents")
    p_igit.add_argument("repo", help="Path to git repository")
    p_igit.add_argument(
        "--since",
        default=None,
        help="Only commits since this date (e.g. '6m', '2025-01-01')",
    )
    p_igit.add_argument(
        "--until",
        default=None,
        help="Only commits until this date (e.g. '2026-02-20')",
    )
    p_igit.add_argument(
        "--author",
        default=None,
        help="Filter commits by author name or email (e.g. 'Alice', 'alice@example.com')",
    )
    p_igit.add_argument(
        "--max-commits",
        type=int,
        default=10,
        help="Max commits per file, most recent (default: 10)",
    )
    p_igit.add_argument(
        "--include",
        default=None,
        help="Only include files matching this glob (e.g. 'src/**')",
    )
    p_igit.add_argument(
        "--exclude",
        default=None,
        help="Skip files matching this glob (e.g. '*.lock,package.json')",
    )
    p_igit.add_argument("--dry-run", action="store_true", help="Preview without ingesting")
    p_igit.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest all files, ignoring content hash (skip-if-unchanged)",
    )
    p_igit.add_argument("--embed", action="store_true", help="Embed chunks after ingestion")
    p_igit.add_argument(
        "--merges",
        action="store_true",
        help="Include merge commits (excluded by default)",
    )

    # diff
    p_diff = sub.add_parser("diff", help="Show what would change on re-ingest")
    p_diff.add_argument("path", help="File or directory to compare")

    # check
    sub.add_parser("check", help="Verify database connection and schema")

    # setup
    p_setup = sub.add_parser(
        "setup",
        help="Wire the server into the MCP clients on this machine",
        description=(
            "Render (and with --write, install) the client config that points at the "
            "gnosis-mcp running this command. Prints by default."
        ),
    )
    p_setup.add_argument(
        "--client",
        action="append",
        choices=clients.client_names(),
        help="Client to configure; repeatable. Default: every client detected here.",
    )
    p_setup.add_argument(
        "--write", action="store_true", help="Apply the changes (default: preview)"
    )
    p_setup.add_argument(
        "--no-cli",
        action="store_true",
        help="Edit config files directly instead of running each client's own `mcp add`",
    )
    p_setup.add_argument("--dsh-profile", help="DeepSeek Harness profile to patch (default: web)")
    p_setup.add_argument("--json", action="store_true", help="Emit JSON only")
    p_setup.add_argument(
        "--list", dest="list_clients", action="store_true", help="List supported clients and exit"
    )

    # doctor
    p_doctor = sub.add_parser(
        "doctor",
        help="Check the database, the client wiring, and whether anything calls it",
        description=(
            "A superset of `check`: database health, which clients are wired, and who "
            "the access log says has actually called this server."
        ),
    )
    p_doctor.add_argument(
        "--days", type=int, default=30, help="Usage window in days (default: 30)"
    )
    p_doctor.add_argument(
        "--strict", action="store_true", help="Exit 1 when wired but never called (for CI)"
    )
    p_doctor.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip `dsh --dump-config`, which validates the harness composition",
    )
    p_doctor.add_argument("--dsh-profile", help="DeepSeek Harness profile to inspect")
    p_doctor.add_argument("--json", action="store_true", help="Emit JSON only")

    # cleanup
    cleanup_parser = sub.add_parser("cleanup", help="Purge old access log entries")
    cleanup_parser.add_argument(
        "--days", type=int, default=90, help="Delete entries older than N days (default: 90)"
    )

    sub.add_parser(
        "fix-link-types",
        help="Migrate git-history links to proper relation types",
    )

    p_eval = sub.add_parser("eval", help="Run retrieval quality eval (Hit@K, MRR, Precision@K)")
    p_eval.add_argument("--json", action="store_true", help="Emit JSON only")

    p_savings = sub.add_parser(
        "savings",
        help="Estimated token savings from logged MCP tool calls",
    )
    p_savings.add_argument("--days", type=int, default=30, help="Look back N days (default: 30)")
    p_savings.add_argument("--json", action="store_true", help="Emit JSON only")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "serve": cmd_serve,
        "init-db": cmd_init_db,
        "ingest": cmd_ingest,
        "ingest-git": cmd_ingest_git,
        "crawl": cmd_crawl,
        "search": cmd_search,
        "embed": cmd_embed,
        "stats": cmd_stats,
        "export": cmd_export,
        "diff": cmd_diff,
        "check": cmd_check,
        "setup": cmd_setup,
        "doctor": cmd_doctor,
        "cleanup": cmd_cleanup,
        "fix-link-types": cmd_fix_link_types,
        "eval": cmd_eval,
        "prune": cmd_prune,
        "savings": cmd_savings,
    }
    # Handlers return None everywhere except `check`, which reports health via
    # its return value. sys.exit (not a bare `return`) is what carries that
    # status through both entry points: the `gnosis-mcp` console script wraps
    # main() in sys.exit(), while `python -m gnosis_mcp` calls main() directly.
    exit_code = commands[args.command](args)
    if exit_code:
        sys.exit(exit_code)
