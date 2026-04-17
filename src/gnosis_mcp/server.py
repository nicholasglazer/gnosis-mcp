"""FastMCP server with documentation tools and resources."""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from gnosis_mcp.db import AppContext, app_lifespan

__all__ = ["mcp"]

log = logging.getLogger("gnosis_mcp")

mcp = FastMCP("gnosis-mcp", lifespan=app_lifespan, streamable_http_path="/mcp")

# In-memory search counters for observability (reset on server restart)
_search_stats: dict[str, int] = {"total": 0, "misses": 0, "hybrid": 0, "keyword": 0}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_ctx() -> AppContext:
    return mcp.get_context().request_context.lifespan_context


def _is_private_address(host: str) -> bool:
    """Resolve host and check if any resolved address is private/loopback/link-local/multicast."""
    try:
        _, _, addrs = socket.gethostbyname_ex(host)
    except (socket.gaierror, socket.herror):
        return True  # unresolvable host → treat as unsafe
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            return True
    return False


async def _notify_webhook(ctx: AppContext, action: str, path: str) -> None:
    """POST to webhook URL if configured. Fire-and-forget, never raises."""
    url = ctx.config.webhook_url
    if not url:
        return
    try:
        import asyncio
        import urllib.request

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            log.warning("webhook URL has unsupported scheme or missing host: %s", url)
            return
        if not ctx.config.webhook_allow_private:
            is_private = await asyncio.to_thread(_is_private_address, parsed.hostname)
            if is_private:
                log.warning(
                    "webhook URL resolves to private/loopback address; refusing to POST: %s",
                    url,
                )
                return

        payload = json.dumps(
            {"action": action, "path": path, "timestamp": datetime.now(timezone.utc).isoformat()}
        ).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )

        await asyncio.to_thread(urllib.request.urlopen, req, timeout=ctx.config.webhook_timeout)
        log.info("webhook notified: action=%s path=%s", action, path)
    except Exception:
        log.warning("webhook failed for %s (url=%s)", path, url, exc_info=True)


def _format_search_result(row: dict, preview_chars: int) -> dict:
    """Shape a backend search row as the MCP-tool result dict.

    Shared by `search_docs` and `search_git_history` so their output stays in lockstep.
    """
    content = row["content"]
    item = {
        "file_path": row["file_path"],
        "title": row["title"],
        "content_preview": (
            content[:preview_chars] + "..." if len(content) > preview_chars else content
        ),
        "score": round(float(row["score"]), 4),
    }
    if row.get("highlight"):
        item["highlight"] = row["highlight"]
    return item


async def _log_access(
    ctx: AppContext,
    file_paths: list[str],
    tool: str,
    query: str | None = None,
) -> None:
    """Log document access events. Fire-and-forget, never raises."""
    if not ctx.config.access_log:
        return
    try:
        for fp in file_paths:
            await ctx.backend.log_access(fp, tool=tool, query=query)
    except Exception:
        log.debug("access log failed", exc_info=True)


# ---------------------------------------------------------------------------
# MCP Resources — browsable document index and content
# ---------------------------------------------------------------------------


@mcp.resource("gnosis://docs")
async def list_docs() -> str:
    """List all documents with title, category, and chunk count."""
    ctx = await _get_ctx()
    try:
        docs = await ctx.backend.list_docs()
        return json.dumps(docs, indent=2)
    except Exception as e:
        log.exception("list_docs resource failed")
        return json.dumps(
            {"error": f"{type(e).__name__}: {e}", "hint": "Run `gnosis-mcp check` to diagnose."}
        )


@mcp.resource("gnosis://docs/{path}")
async def read_doc_resource(path: str) -> str:
    """Read a document by path as an MCP resource. Reassembles chunks."""
    ctx = await _get_ctx()
    try:
        rows = await ctx.backend.get_doc(path)
        if not rows:
            return json.dumps({"error": f"No document at: {path}"})
        return "\n\n".join(r["content"] for r in rows)
    except Exception as e:
        log.exception("read_doc_resource failed for path=%s", path)
        return json.dumps(
            {"error": f"{type(e).__name__}: {e}", "hint": "Run `gnosis-mcp check` to diagnose."}
        )


@mcp.resource("gnosis://categories")
async def list_categories() -> str:
    """List all document categories with counts."""
    ctx = await _get_ctx()
    try:
        cats = await ctx.backend.list_categories()
        return json.dumps(cats, indent=2)
    except Exception as e:
        log.exception("list_categories resource failed")
        return json.dumps(
            {"error": f"{type(e).__name__}: {e}", "hint": "Run `gnosis-mcp check` to diagnose."}
        )


# ---------------------------------------------------------------------------
# Read Tools (original 3)
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_docs(
    query: str,
    category: str | None = None,
    limit: int = 5,
    query_embedding: list[float] | None = None,
    rerank: bool | None = None,
) -> str:
    """Search documentation using keyword or hybrid semantic+keyword search.

    Args:
        query: Search query text.
        category: Optional category filter (e.g. "guides", "architecture", "ops").
        limit: Maximum results (default 5, server-configurable upper bound).
        query_embedding: Optional pre-computed embedding vector for hybrid search.
            When provided, combines keyword (tsvector) and semantic (cosine) scoring.
        rerank: Rerank results with a cross-encoder before returning.
            None = follow `GNOSIS_MCP_RERANK_ENABLED`. Requires the [reranking] extra.
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    if not query or not query.strip():
        return json.dumps({"error": "Empty query. Provide a search term."})

    if len(query) > cfg.max_query_chars:
        return json.dumps(
            {"error": f"Query exceeds {cfg.max_query_chars} chars. Shorten the query."}
        )

    use_rerank = cfg.rerank_enabled if rerank is None else rerank
    fetch_limit = max(limit, cfg.rerank_pool) if use_rerank else limit
    fetch_limit = max(1, min(max(cfg.search_limit_max, cfg.rerank_pool), fetch_limit))

    limit = max(1, min(cfg.search_limit_max, limit))
    preview = cfg.content_preview_chars

    # Auto-embed query when local provider is available and no embedding provided
    if query_embedding is None and cfg.embed_provider == "local":
        try:
            from gnosis_mcp.embed import embed_texts

            vectors = embed_texts(
                [query], provider="local", model=cfg.embed_model, dim=cfg.embed_dim
            )
            query_embedding = vectors[0] if vectors else None
        except ImportError:
            pass  # [embeddings] not installed

    try:
        results = await ctx.backend.search(
            query,
            category=category,
            limit=fetch_limit,
            query_embedding=query_embedding,
        )

        if use_rerank and results:
            try:
                from gnosis_mcp.rerank import get_reranker

                reranker = get_reranker(cfg.rerank_model)
                import asyncio as _asyncio

                results = await _asyncio.to_thread(
                    reranker.rerank, query, results, text_key="content", top_k=limit
                )
            except ImportError:
                log.warning(
                    "Rerank requested but [reranking] extra not installed — returning unranked"
                )
                results = results[:limit]
            except Exception:
                log.exception("Rerank failed; falling back to unranked results")
                results = results[:limit]
        else:
            results = results[:limit]

        items = [_format_search_result(r, preview) for r in results]

        # Log query for observability
        top_path = items[0]["file_path"] if items else None
        top_score = items[0]["score"] if items else None
        search_mode = "hybrid" if query_embedding else "keyword"
        _search_stats["total"] += 1
        _search_stats[search_mode] += 1
        if not items:
            _search_stats["misses"] += 1
        log.info(
            "search: query=%r mode=%s results=%d top=%s score=%s cat=%s",
            query,
            search_mode,
            len(items),
            top_path,
            top_score,
            category,
        )

        # Log top result paths for access tracking
        if items:
            await _log_access(ctx, [it["file_path"] for it in items[:3]], "search_docs", query)

        return json.dumps(items, indent=2)
    except Exception as e:
        log.exception("search_docs failed")
        return json.dumps(
            {
                "error": f"{type(e).__name__}: {e}",
                "hint": "Run `gnosis-mcp check` to verify the DB is initialised and reachable.",
            }
        )


@mcp.tool()
async def get_doc(path: str, max_length: int | None = None) -> str:
    """Get full document content by file path. Reassembles all chunks in order.

    Args:
        path: Document file path (e.g. "curated/guides/design-system.md").
        max_length: Optional max characters to return. Truncates with "..." if exceeded.
            Useful for large documents when you only need a preview.
    """
    ctx = await _get_ctx()

    try:
        rows = await ctx.backend.get_doc(path)

        if not rows:
            return json.dumps({"error": f"No document found at path: {path}"})

        first = rows[0]
        content = "\n\n".join(r["content"] for r in rows)
        truncated = False
        if max_length and len(content) > max_length:
            content = content[:max_length] + "..."
            truncated = True

        result = {
            "title": first["title"],
            "content": content,
            "category": first["category"],
            "audience": first["audience"],
            "tags": first["tags"],
        }
        if truncated:
            result["truncated"] = True
        await _log_access(ctx, [path], "get_doc")
        return json.dumps(result, indent=2)
    except Exception:
        log.exception("get_doc failed for path=%s", path)
        return json.dumps({"error": f"Failed to retrieve document: {path}"})


@mcp.tool()
async def search_git_history(
    query: str,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    file_path: str | None = None,
    limit: int = 5,
) -> str:
    """Search git commit history documents. Searches the git-history category.

    Args:
        query: Search query text (commit messages, file names, authors).
        author: Filter results by author name or email substring.
        since: Filter results to commits after this date (YYYY-MM-DD).
        until: Filter results to commits before this date (YYYY-MM-DD).
        file_path: Filter results to a specific file's history.
        limit: Maximum results (default 5).
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    if not query or not query.strip():
        return json.dumps({"error": "Empty query. Provide a search term."})

    limit = max(1, min(cfg.search_limit_max, limit))

    try:
        # Search within git-history category
        search_category = "git-history"
        results = await ctx.backend.search(
            query,
            category=search_category,
            limit=limit * 3,  # over-fetch for post-filtering
        )

        # Post-filter by author, date, file_path
        filtered = []
        for r in results:
            content = r.get("content", "")
            fp = r.get("file_path", "")
            title = r.get("title", "")

            if author and author.lower() not in content.lower():
                continue
            # Titles are formatted as "YYYY-MM-DD: subject (hash)"
            title_date = title[:10] if len(title) >= 10 else ""
            if since and title_date < since:
                continue
            if until and title_date > until:
                continue
            if file_path and file_path not in fp:
                continue

            filtered.append(r)

        filtered = filtered[:limit]

        preview = cfg.content_preview_chars
        items = [_format_search_result(r, preview) for r in filtered]

        log.info(
            "search_git_history: query=%r results=%d author=%s file=%s",
            query,
            len(items),
            author,
            file_path,
        )
        return json.dumps(items, indent=2)
    except Exception:
        log.exception("search_git_history failed")
        return json.dumps({"error": f"Search failed for query: {query!r}"})


@mcp.tool()
async def get_related(
    path: str,
    depth: int = 1,
    relation_type: str | None = None,
    include_titles: bool = False,
) -> str:
    """Find documents related to a given path via incoming and outgoing links.

    Args:
        path: Document file path to find related documents for.
        depth: Traversal depth (1=direct neighbors, 2+=multi-hop, max 3).
        relation_type: Filter by link type (e.g. 'relates_to', 'content_link', 'git_co_change').
        include_titles: Include title and category for each related document.
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    try:
        results = await ctx.backend.get_related(
            path,
            depth=max(1, min(depth, 3)),
            relation_type=relation_type or None,
            include_titles=include_titles,
        )

        if results is None:
            return json.dumps(
                {
                    "message": f"{cfg.qualified_links_table} table does not exist. "
                    "Related document lookup is not available.",
                    "results": [],
                },
                indent=2,
            )

        return json.dumps(results, indent=2, default=str)
    except Exception:
        log.exception("get_related failed for path=%s", path)
        return json.dumps({"error": f"Failed to find related documents for: {path}"})


@mcp.tool()
async def get_context(
    topic: str | None = None,
    limit: int = 10,
    category: str | None = None,
) -> str:
    """Get the most important documents as a lightweight context primer.

    Returns a compact summary of top documents based on access frequency.
    Use at the start of a session for quick orientation.

    Args:
        topic: Optional topic to focus on. Combines search with access data.
        limit: Maximum documents to return (default 10).
        category: Optional category filter.
    """
    ctx = await _get_ctx()
    cfg = ctx.config
    limit = max(1, min(cfg.search_limit_max, limit))
    preview = cfg.content_preview_chars

    try:
        docs = []

        if topic:
            results = await ctx.backend.search(
                topic,
                category=category,
                limit=limit,
            )
            top_accessed = await ctx.backend.get_top_accessed(
                limit=limit,
                days=30,
                category=category,
            )
            access_map = {r["file_path"]: r["access_count"] for r in top_accessed}
            for r in results:
                content = r["content"]
                docs.append(
                    {
                        "file_path": r["file_path"],
                        "title": r["title"],
                        "category": r.get("category"),
                        "summary": (
                            content[:preview] + "..." if len(content) > preview else content
                        ),
                        "access_count": access_map.get(r["file_path"], 0),
                    }
                )
        else:
            top_accessed = await ctx.backend.get_top_accessed(
                limit=limit,
                days=30,
                category=category,
            )
            for r in top_accessed:
                chunks = await ctx.backend.get_doc(r["file_path"])
                summary = ""
                if chunks:
                    content = chunks[0]["content"]
                    summary = content[:preview] + "..." if len(content) > preview else content
                docs.append(
                    {
                        "file_path": r["file_path"],
                        "title": r["title"],
                        "category": r["category"],
                        "summary": summary,
                        "access_count": r["access_count"],
                    }
                )

        stats_data = await ctx.backend.stats()
        stats = {
            "total_docs": stats_data["docs"],
            "total_chunks": stats_data["chunks"],
            "categories": len(stats_data.get("categories", [])),
        }

        log.info("get_context: topic=%r docs=%d", topic, len(docs))
        return json.dumps({"docs": docs, "stats": stats}, indent=2)
    except Exception:
        log.exception("get_context failed")
        return json.dumps({"error": "Failed to get context"})


@mcp.tool()
async def get_graph_stats(category: str | None = None) -> str:
    """Get knowledge graph topology: orphans, hubs, connection stats.

    Args:
        category: Optional category filter for orphan detection.
    """
    ctx = await _get_ctx()

    try:
        stats = await ctx.backend.get_graph_stats(category=category)

        if stats is None:
            return json.dumps(
                {"message": "Links table does not exist.", "stats": {}},
                indent=2,
            )

        return json.dumps(stats, indent=2, default=str)
    except Exception:
        log.exception("get_graph_stats failed")
        return json.dumps({"error": "Failed to get graph stats"})


# ---------------------------------------------------------------------------
# Write Tools — gated behind GNOSIS_MCP_WRITABLE=true
# ---------------------------------------------------------------------------


@mcp.tool()
async def upsert_doc(
    path: str,
    content: str,
    title: str | None = None,
    category: str | None = None,
    audience: str = "all",
    tags: list[str] | None = None,
    embeddings: list[list[float]] | None = None,
) -> str:
    """Insert or replace a document. Requires GNOSIS_MCP_WRITABLE=true.

    Splits content into chunks if it exceeds the configured chunk size (at paragraph boundaries).
    Existing chunks for this path are deleted and replaced.

    Args:
        path: Document file path (e.g. "guides/quickstart.md").
        content: Full document content (markdown or plain text).
        title: Document title (extracted from first H1 if not provided).
        category: Document category (e.g. "guides", "architecture").
        audience: Target audience (default "all").
        tags: Optional list of tags.
        embeddings: Optional pre-computed embedding vectors, one per chunk.
            Length must match the number of chunks after splitting.
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    if not cfg.writable:
        return json.dumps(
            {"error": "Write operations disabled. Set GNOSIS_MCP_WRITABLE=true to enable."}
        )

    if len(content.encode("utf-8")) > cfg.max_doc_bytes:
        return json.dumps(
            {"error": f"Content exceeds max_doc_bytes ({cfg.max_doc_bytes}). Split the document."}
        )

    # Auto-extract title from first heading if not provided
    if title is None:
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break

    # Split into chunks at paragraph boundaries
    chunks = _split_chunks(content, max_size=cfg.chunk_size)

    # Validate embeddings count matches chunks
    if embeddings is not None and len(embeddings) != len(chunks):
        return json.dumps(
            {
                "error": f"Embeddings count ({len(embeddings)}) does not match "
                f"chunk count ({len(chunks)}). Provide one embedding per chunk."
            }
        )

    try:
        count = await ctx.backend.upsert_doc(
            path,
            chunks,
            title=title,
            category=category,
            audience=audience,
            tags=tags,
            embeddings=embeddings,
        )
        await _notify_webhook(ctx, "upsert", path)
        log.info("upsert_doc: path=%s chunks=%d", path, count)
        return json.dumps({"path": path, "chunks": count, "action": "upserted"})
    except Exception:
        log.exception("upsert_doc failed for path=%s", path)
        return json.dumps({"error": f"Failed to upsert document: {path}"})


@mcp.tool()
async def delete_doc(path: str) -> str:
    """Delete a document and all its chunks. Requires GNOSIS_MCP_WRITABLE=true.

    Args:
        path: Document file path to delete.
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    if not cfg.writable:
        return json.dumps(
            {"error": "Write operations disabled. Set GNOSIS_MCP_WRITABLE=true to enable."}
        )

    try:
        result = await ctx.backend.delete_doc(path)

        if result["chunks_deleted"] == 0:
            return json.dumps({"error": f"No document found at path: {path}"})

        await _notify_webhook(ctx, "delete", path)
        log.info(
            "delete_doc: path=%s chunks=%d links=%d",
            path,
            result["chunks_deleted"],
            result["links_deleted"],
        )
        return json.dumps(
            {
                "path": path,
                "chunks_deleted": result["chunks_deleted"],
                "links_deleted": result["links_deleted"],
                "action": "deleted",
            }
        )
    except Exception:
        log.exception("delete_doc failed for path=%s", path)
        return json.dumps({"error": f"Failed to delete document: {path}"})


@mcp.tool()
async def update_metadata(
    path: str,
    title: str | None = None,
    category: str | None = None,
    audience: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update metadata fields on all chunks of a document. Requires GNOSIS_MCP_WRITABLE=true.

    Only provided fields are updated; omitted fields remain unchanged.

    Args:
        path: Document file path to update.
        title: New title (applied to all chunks).
        category: New category.
        audience: New audience.
        tags: New tags list.
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    if not cfg.writable:
        return json.dumps(
            {"error": "Write operations disabled. Set GNOSIS_MCP_WRITABLE=true to enable."}
        )

    if title is None and category is None and audience is None and tags is None:
        return json.dumps(
            {
                "error": "No fields to update. Provide at least one of: title, category, audience, tags."
            }
        )

    try:
        affected = await ctx.backend.update_metadata(
            path, title=title, category=category, audience=audience, tags=tags
        )

        if affected == 0:
            return json.dumps({"error": f"No document found at path: {path}"})

        await _notify_webhook(ctx, "update_metadata", path)
        log.info("update_metadata: path=%s chunks_updated=%d", path, affected)
        return json.dumps({"path": path, "chunks_updated": affected, "action": "metadata_updated"})
    except Exception:
        log.exception("update_metadata failed for path=%s", path)
        return json.dumps({"error": f"Failed to update metadata for: {path}"})


# ---------------------------------------------------------------------------
# Chunk splitting helper
# ---------------------------------------------------------------------------


def _split_chunks(content: str, max_size: int = 4000) -> list[str]:
    """Split content into chunks at paragraph boundaries.

    Protects fenced code blocks and tables from being split mid-block.
    """
    if len(content) <= max_size:
        return [content]

    from gnosis_mcp.ingest import _split_paragraphs_safe

    return _split_paragraphs_safe(content, max_size) or [content]
