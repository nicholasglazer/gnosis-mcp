"""REST API endpoints for gnosis-mcp.

Provides a lightweight HTTP API alongside the MCP server.
Enabled via GNOSIS_MCP_REST=true or --rest flag on serve.

Endpoints:
    GET /health                          — Server health + stats
    GET /api/search?q=&limit=&category=  — Search documents
    GET /api/docs/{path}                 — Get document by path
    GET /api/docs/{path}/related         — Get related documents
    GET /api/categories                  — List categories
"""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from gnosis_mcp import __version__
from gnosis_mcp.backend import DocBackend, create_backend
from gnosis_mcp.config import GnosisMcpConfig

__all__ = ["create_rest_app", "create_combined_app"]

log = logging.getLogger("gnosis_mcp.rest")


# ---------------------------------------------------------------------------
# Backend lifecycle
# ---------------------------------------------------------------------------


def _make_lifespan(config: GnosisMcpConfig):
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[dict]:
        backend = create_backend(config)
        await backend.startup()
        try:
            yield {"backend": backend, "config": config}
        finally:
            await backend.shutdown()

    return lifespan


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class ApiKeyMiddleware:
    """Simple Bearer token auth. Skips non-http scopes (e.g. lifespan).

    ``/health`` is always public — load balancers, monitoring, and CI probes
    rely on it. Everything else under ``/api/`` requires a matching Bearer
    token when one is configured.
    """

    # Paths that must never be gated by auth. Callers can extend via
    # ``GNOSIS_MCP_PUBLIC_PATHS`` (comma-separated) if they add more probes.
    PUBLIC_PATHS: tuple[str, ...] = ("/health",)

    def __init__(self, app, api_key: str, public_paths: tuple[str, ...] | None = None) -> None:
        self.app = app
        self.api_key = api_key
        self.public_paths = public_paths or self.PUBLIC_PATHS

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path in self.public_paths:
                await self.app(scope, receive, send)
                return
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            valid = auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], self.api_key)
            if not valid:
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Log method, path, status, duration (ms). Skips /health."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/health":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        start = time.perf_counter()
        status_holder = {"code": 0}

        async def wrapped_send(message):
            if message.get("type") == "http.response.start":
                status_holder["code"] = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            log.info(
                "%s %s -> %d (%.1f ms)",
                method,
                path,
                status_holder["code"],
                duration_ms,
            )


class CorsMiddleware:
    """Minimal CORS middleware. Handles preflight and adds CORS headers."""

    def __init__(self, app, origins: list[str]) -> None:
        self.app = app
        self.origins = origins
        self.allow_all = "*" in origins

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()

        if scope.get("method") == "OPTIONS":
            response_headers = self._cors_headers(origin)
            response_headers["access-control-allow-methods"] = "GET, OPTIONS"
            response_headers["access-control-allow-headers"] = "Authorization, Content-Type"
            response_headers["access-control-max-age"] = "86400"
            response = JSONResponse({}, status_code=204, headers=response_headers)
            await response(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                cors = self._cors_headers(origin)
                extra = [(k.encode(), v.encode()) for k, v in cors.items()]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_cors)

    def _cors_headers(self, origin: str) -> dict[str, str]:
        if self.allow_all:
            return {"access-control-allow-origin": "*"}
        if origin in self.origins:
            return {
                "access-control-allow-origin": origin,
                "vary": "Origin",
            }
        return {}


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def _backend(request: Request) -> DocBackend:
    return request.state.backend


def _config(request: Request) -> GnosisMcpConfig:
    return request.state.config


async def health(request: Request) -> JSONResponse:
    backend = _backend(request)
    cfg = _config(request)
    try:
        from gnosis_mcp.server import _search_stats

        h = await backend.check_health()
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "backend": h.get("backend", cfg.backend),
                # "docs" is the distinct file_path count — what users think of as docs.
                # "chunks" is the post-split row count. Pre-0.11.3 /health reported
                # chunks_count under the "docs" label, which read as off-by-~4x.
                "docs": h.get("docs_count", h.get("chunks_count", 0)),
                "chunks": h.get("chunks_count", 0),
                "search_stats": dict(_search_stats),
            }
        )
    except Exception:
        log.exception("health check failed")
        return JSONResponse({"status": "error"}, status_code=500)


async def search(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "").strip()
    if not q:
        return JSONResponse({"error": "Query parameter 'q' is required"}, status_code=400)

    backend = _backend(request)
    cfg = _config(request)

    try:
        limit_raw = request.query_params.get("limit", "10")
        limit = max(1, min(int(limit_raw), cfg.search_limit_max))
    except (ValueError, TypeError):
        limit = 10

    category = request.query_params.get("category") or None

    # Auto-embed for hybrid search when local provider is configured
    query_embedding = None
    if cfg.embed_provider == "local":
        try:
            from gnosis_mcp.embed import embed_texts

            vectors = embed_texts([q], provider="local", model=cfg.embed_model, dim=cfg.embed_dim)
            query_embedding = vectors[0] if vectors else None
        except ImportError:
            pass

    try:
        results = await backend.search(
            q,
            category=category,
            limit=limit,
            query_embedding=query_embedding,
        )
        preview = cfg.content_preview_chars
        items = []
        for r in results:
            content = r["content"]
            items.append(
                {
                    "file_path": r["file_path"],
                    "title": r["title"],
                    "content_preview": (
                        content[:preview] + "..." if len(content) > preview else content
                    ),
                    "score": round(float(r["score"]), 4),
                    "category": r.get("category"),
                    "highlight": r.get("highlight"),
                }
            )
        return JSONResponse({"results": items, "query": q, "count": len(items)})
    except Exception:
        log.exception("search failed")
        return JSONResponse({"error": "Search failed"}, status_code=500)


async def get_doc(request: Request) -> JSONResponse:
    path = request.path_params["path"]
    backend = _backend(request)

    try:
        rows = await backend.get_doc(path)
        if not rows:
            return JSONResponse({"error": f"Not found: {path}"}, status_code=404)

        first = rows[0]
        content = "\n\n".join(r["content"] for r in rows)
        return JSONResponse(
            {
                "title": first["title"],
                "content": content,
                "category": first.get("category"),
                "audience": first.get("audience"),
                "tags": first.get("tags"),
                "chunks": len(rows),
            }
        )
    except Exception:
        log.exception("get_doc failed for path=%s", path)
        return JSONResponse({"error": "Failed to retrieve document"}, status_code=500)


async def get_related(request: Request) -> JSONResponse:
    path = request.path_params["path"]
    backend = _backend(request)
    try:
        depth = int(request.query_params.get("depth", "1"))
    except (ValueError, TypeError):
        depth = 1
    relation_type = request.query_params.get("relation_type")
    include_titles = request.query_params.get("include_titles", "").lower() in ("1", "true")

    try:
        results = await backend.get_related(
            path,
            depth=min(depth, 3),
            relation_type=relation_type or None,
            include_titles=include_titles,
        )
        if results is None:
            return JSONResponse({"results": [], "message": "Links table not available"})
        return JSONResponse({"results": results})
    except Exception:
        log.exception("get_related failed for path=%s", path)
        return JSONResponse({"error": "Failed to find related documents"}, status_code=500)


async def rest_get_graph_stats(request: Request) -> JSONResponse:
    backend = _backend(request)
    category = request.query_params.get("category")

    try:
        stats = await backend.get_graph_stats(category=category or None)
        if stats is None:
            return JSONResponse({"stats": {}, "message": "Links table not available"})
        return JSONResponse({"stats": stats})
    except Exception:
        log.exception("get_graph_stats failed")
        return JSONResponse({"error": "Failed to get graph stats"}, status_code=500)


async def list_categories(request: Request) -> JSONResponse:
    backend = _backend(request)
    try:
        cats = await backend.list_categories()
        return JSONResponse(cats)
    except Exception:
        log.exception("list_categories failed")
        return JSONResponse({"error": "Failed to list categories"}, status_code=500)


async def get_context(request: Request) -> JSONResponse:
    """Context primer endpoint."""
    backend = _backend(request)
    cfg = _config(request)
    topic = request.query_params.get("topic") or None
    cat = request.query_params.get("category") or None
    try:
        limit_str = request.query_params.get("limit", "10")
        limit = max(1, min(int(limit_str), cfg.search_limit_max))
    except (ValueError, TypeError):
        limit = 10

    preview = cfg.content_preview_chars
    try:
        docs = []
        if topic:
            results = await backend.search(topic, category=cat, limit=limit)
            top_accessed = await backend.get_top_accessed(
                limit=limit,
                days=30,
                category=cat,
            )
            access_map = {r["file_path"]: r["access_count"] for r in top_accessed}
            for r in results:
                content = r["content"]
                docs.append(
                    {
                        "file_path": r["file_path"],
                        "title": r["title"],
                        "category": r.get("category"),
                        "summary": content[:preview] + "..."
                        if len(content) > preview
                        else content,
                        "access_count": access_map.get(r["file_path"], 0),
                    }
                )
        else:
            top_accessed = await backend.get_top_accessed(
                limit=limit,
                days=30,
                category=cat,
            )
            for r in top_accessed:
                chunks = await backend.get_doc(r["file_path"])
                summary = ""
                if chunks:
                    c = chunks[0]["content"]
                    summary = c[:preview] + "..." if len(c) > preview else c
                docs.append(
                    {
                        "file_path": r["file_path"],
                        "title": r["title"],
                        "category": r["category"],
                        "summary": summary,
                        "access_count": r["access_count"],
                    }
                )

        stats_data = await backend.stats()
        stats = {
            "total_docs": stats_data["docs"],
            "total_chunks": stats_data["chunks"],
            "categories": len(stats_data.get("categories", [])),
        }
        return JSONResponse({"docs": docs, "stats": stats})
    except Exception:
        log.exception("get_context REST failed")
        return JSONResponse({"error": "Failed to get context"}, status_code=500)


# ---------------------------------------------------------------------------
# App factories
# ---------------------------------------------------------------------------


def _make_routes() -> list:
    """Build the REST route list."""
    return [
        Route("/health", health, methods=["GET"]),
        Route("/api/search", search, methods=["GET"]),
        Route("/api/context", get_context, methods=["GET"]),
        Route("/api/graph/stats", rest_get_graph_stats, methods=["GET"]),
        Route("/api/docs/{path:path}/related", get_related, methods=["GET"]),
        Route("/api/docs/{path:path}", get_doc, methods=["GET"]),
        Route("/api/categories", list_categories, methods=["GET"]),
    ]


def create_rest_app(config: GnosisMcpConfig) -> Starlette:
    """Create a standalone Starlette app with REST API routes and its own backend lifespan."""
    app = Starlette(routes=_make_routes(), lifespan=_make_lifespan(config))

    # Wrap with request logging (innermost — sees actual status codes)
    app = RequestLoggingMiddleware(app)

    # Wrap with API key auth (inside CORS so preflight bypasses auth)
    if config.api_key:
        app = ApiKeyMiddleware(app, config.api_key)

    # Wrap with CORS last (outermost) — must handle OPTIONS before auth check
    if config.cors_origins:
        origins = [o.strip() for o in config.cors_origins.split(",")]
        app = CorsMiddleware(app, origins)

    return app


def create_combined_app(mcp_server, transport: str, config: GnosisMcpConfig) -> Starlette:
    """Create a combined ASGI app serving both REST and MCP on the same port.

    REST routes are mounted first (specific paths), MCP is the catch-all.
    The REST backend has its own lifespan; MCP manages its own state.
    """
    if transport == "sse":
        mcp_app = mcp_server.sse_app()
    else:
        mcp_app = mcp_server.streamable_http_app()

    # REST routes first, then MCP as catch-all
    routes = _make_routes()
    routes.append(Mount("/", app=mcp_app))

    app = Starlette(routes=routes, lifespan=_make_lifespan(config))

    app = RequestLoggingMiddleware(app)

    if config.api_key:
        app = ApiKeyMiddleware(app, config.api_key)

    if config.cors_origins:
        origins = [o.strip() for o in config.cors_origins.split(",")]
        app = CorsMiddleware(app, origins)

    return app
