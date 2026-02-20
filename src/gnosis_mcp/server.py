"""FastMCP server with documentation tools and resources."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from gnosis_mcp.db import AppContext, app_lifespan

__all__ = ["mcp"]

log = logging.getLogger("gnosis_mcp")

mcp = FastMCP("gnosis-mcp", lifespan=app_lifespan, streamable_http_path="/mcp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_ctx() -> AppContext:
    return mcp.get_context().request_context.lifespan_context


async def _notify_webhook(ctx: AppContext, action: str, path: str) -> None:
    """POST to webhook URL if configured. Fire-and-forget, never raises."""
    url = ctx.config.webhook_url
    if not url:
        return
    try:
        import urllib.request

        payload = json.dumps(
            {"action": action, "path": path, "timestamp": datetime.now(timezone.utc).isoformat()}
        ).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=ctx.config.webhook_timeout)
        log.info("webhook notified: action=%s path=%s", action, path)
    except Exception:
        log.warning("webhook failed for %s (url=%s)", path, url, exc_info=True)


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
    except Exception:
        log.exception("list_docs resource failed")
        return json.dumps({"error": "Failed to list documents"})


@mcp.resource("gnosis://docs/{path}")
async def read_doc_resource(path: str) -> str:
    """Read a document by path as an MCP resource. Reassembles chunks."""
    ctx = await _get_ctx()
    try:
        rows = await ctx.backend.get_doc(path)
        if not rows:
            return json.dumps({"error": f"No document at: {path}"})
        return "\n\n".join(r["content"] for r in rows)
    except Exception:
        log.exception("read_doc_resource failed for path=%s", path)
        return json.dumps({"error": f"Failed to read document: {path}"})


@mcp.resource("gnosis://categories")
async def list_categories() -> str:
    """List all document categories with counts."""
    ctx = await _get_ctx()
    try:
        cats = await ctx.backend.list_categories()
        return json.dumps(cats, indent=2)
    except Exception:
        log.exception("list_categories resource failed")
        return json.dumps({"error": "Failed to list categories"})


# ---------------------------------------------------------------------------
# Read Tools (original 3)
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_docs(
    query: str,
    category: str | None = None,
    limit: int = 5,
    query_embedding: list[float] | None = None,
) -> str:
    """Search documentation using keyword or hybrid semantic+keyword search.

    Args:
        query: Search query text.
        category: Optional category filter (e.g. "guides", "architecture", "ops").
        limit: Maximum results (default 5, server-configurable upper bound).
        query_embedding: Optional pre-computed embedding vector for hybrid search.
            When provided, combines keyword (tsvector) and semantic (cosine) scoring.
    """
    ctx = await _get_ctx()
    cfg = ctx.config
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
            limit=limit,
            query_embedding=query_embedding,
        )
        items = []
        for r in results:
            item = {
                "file_path": r["file_path"],
                "title": r["title"],
                "content_preview": (
                    r["content"][:preview] + "..."
                    if len(r["content"]) > preview
                    else r["content"]
                ),
                "score": round(float(r["score"]), 4),
            }
            if r.get("highlight"):
                item["highlight"] = r["highlight"]
            items.append(item)
        return json.dumps(items, indent=2)
    except Exception:
        log.exception("search_docs failed")
        return json.dumps({"error": f"Search failed for query: {query!r}"})


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
        return json.dumps(result, indent=2)
    except Exception:
        log.exception("get_doc failed for path=%s", path)
        return json.dumps({"error": f"Failed to retrieve document: {path}"})


@mcp.tool()
async def get_related(path: str) -> str:
    """Find documents related to a given path via incoming and outgoing links.

    Args:
        path: Document file path to find related documents for.
    """
    ctx = await _get_ctx()
    cfg = ctx.config

    try:
        results = await ctx.backend.get_related(path)

        if results is None:
            return json.dumps(
                {
                    "message": f"{cfg.qualified_links_table} table does not exist. "
                    "Related document lookup is not available.",
                    "results": [],
                },
                indent=2,
            )

        return json.dumps(results, indent=2)
    except Exception:
        log.exception("get_related failed for path=%s", path)
        return json.dumps({"error": f"Failed to find related documents for: {path}"})


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
        return json.dumps(
            {"path": path, "chunks_updated": affected, "action": "metadata_updated"}
        )
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
