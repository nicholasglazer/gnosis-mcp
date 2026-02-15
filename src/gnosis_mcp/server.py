"""FastMCP server with documentation tools and resources."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from gnosis_mcp.db import AppContext, app_lifespan

log = logging.getLogger("gnosis_mcp")


def _row_count(status: str) -> int:
    """Extract row count from asyncpg status string (e.g. 'DELETE 5' -> 5, 'UPDATE 0' -> 0)."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0

mcp = FastMCP("gnosis-mcp", lifespan=app_lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_ctx() -> AppContext:
    return mcp.get_context().request_context.lifespan_context


def _union_select(cfg, select_clause: str, where_clause: str = "", order_clause: str = "") -> str:
    """Build a UNION ALL query across all configured chunks tables."""
    tables = cfg.qualified_chunks_tables
    if len(tables) == 1:
        sql = f"SELECT {select_clause} FROM {tables[0]}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        if order_clause:
            sql += f" {order_clause}"
        return sql

    parts = []
    for tbl in tables:
        part = f"SELECT {select_clause} FROM {tbl}"
        if where_clause:
            part += f" WHERE {where_clause}"
        parts.append(part)
    sql = f"SELECT * FROM ({' UNION ALL '.join(parts)}) AS _combined"
    if order_clause:
        sql += f" {order_clause}"
    return sql


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
    cfg = ctx.config
    try:
        async with ctx.pool.acquire() as conn:
            inner = _union_select(
                cfg,
                f"{cfg.col_file_path}, {cfg.col_title}, {cfg.col_category}",
            )
            rows = await conn.fetch(
                f"SELECT {cfg.col_file_path}, "
                f"  MIN({cfg.col_title}) AS title, "
                f"  MIN({cfg.col_category}) AS category, "
                f"  COUNT(*) AS chunks "
                f"FROM ({inner}) AS _all "
                f"GROUP BY {cfg.col_file_path} "
                f"ORDER BY category, {cfg.col_file_path}"
            )
            return json.dumps(
                [
                    {
                        "path": r[cfg.col_file_path],
                        "title": r["title"],
                        "category": r["category"],
                        "chunks": r["chunks"],
                    }
                    for r in rows
                ],
                indent=2,
            )
    except Exception:
        log.exception("list_docs resource failed")
        return json.dumps({"error": "Failed to list documents"})


@mcp.resource("gnosis://docs/{path}")
async def read_doc_resource(path: str) -> str:
    """Read a document by path as an MCP resource. Reassembles chunks."""
    ctx = await _get_ctx()
    cfg = ctx.config
    try:
        async with ctx.pool.acquire() as conn:
            sql = _union_select(
                cfg,
                f"{cfg.col_content}, {cfg.col_chunk_index}",
                f"{cfg.col_file_path} = $1",
                f"ORDER BY {cfg.col_chunk_index}",
            )
            rows = await conn.fetch(sql, path)
            if not rows:
                return json.dumps({"error": f"No document at: {path}"})
            return "\n\n".join(r[cfg.col_content] for r in rows)
    except Exception:
        log.exception("read_doc_resource failed for path=%s", path)
        return json.dumps({"error": f"Failed to read document: {path}"})


@mcp.resource("gnosis://categories")
async def list_categories() -> str:
    """List all document categories with counts."""
    ctx = await _get_ctx()
    cfg = ctx.config
    try:
        async with ctx.pool.acquire() as conn:
            inner = _union_select(
                cfg,
                f"{cfg.col_file_path}, {cfg.col_category}",
                f"{cfg.col_category} IS NOT NULL",
            )
            rows = await conn.fetch(
                f"SELECT {cfg.col_category} AS category, "
                f"  COUNT(DISTINCT {cfg.col_file_path}) AS docs "
                f"FROM ({inner}) AS _all "
                f"GROUP BY {cfg.col_category} "
                f"ORDER BY {cfg.col_category}"
            )
            return json.dumps(
                [{"category": r["category"], "docs": r["docs"]} for r in rows],
                indent=2,
            )
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
) -> str:
    """Search documentation using keyword or hybrid semantic+keyword search.

    Args:
        query: Search query text.
        category: Optional category filter (e.g. "guides", "architecture", "ops").
        limit: Maximum results (1-20, default 5).
    """
    ctx = await _get_ctx()
    cfg = ctx.config
    limit = max(1, min(cfg.search_limit_max, limit))
    preview = cfg.content_preview_chars

    try:
        async with ctx.pool.acquire() as conn:
            if cfg.search_function:
                # Delegate to custom search function (e.g. hybrid semantic+keyword).
                # Custom functions must return: file_path, title, content, category, combined_score.
                # These column names are part of the function contract (not GNOSIS_MCP_COL_* overrides).
                rows = await conn.fetch(
                    f"SELECT * FROM {cfg.search_function}("
                    f"p_query_text := $1, p_categories := $2, p_limit := $3)",
                    query,
                    [category] if category else None,
                    limit,
                )
                results = [
                    {
                        "file_path": r["file_path"],
                        "title": r["title"],
                        "content_preview": (
                            r["content"][:preview] + "..."
                            if len(r["content"]) > preview
                            else r["content"]
                        ),
                        "score": round(float(r.get("combined_score", 0)), 4),
                    }
                    for r in rows
                ]
            else:
                # Built-in tsvector keyword search (respects GNOSIS_MCP_COL_* overrides)
                select = (
                    f"{cfg.col_file_path}, {cfg.col_title}, {cfg.col_content}, "
                    f"{cfg.col_category}, "
                    f"ts_rank({cfg.col_tsv}, websearch_to_tsquery('english', $1)) AS score"
                )
                where = f"{cfg.col_tsv} @@ websearch_to_tsquery('english', $1)"
                if category:
                    where += f" AND {cfg.col_category} = $3"
                sql = _union_select(cfg, select, where, "ORDER BY score DESC LIMIT $2")
                rows = await conn.fetch(
                    sql,
                    query,
                    limit,
                    *([category] if category else []),
                )
                results = [
                    {
                        "file_path": r[cfg.col_file_path],
                        "title": r[cfg.col_title],
                        "content_preview": (
                            r[cfg.col_content][:preview] + "..."
                            if len(r[cfg.col_content]) > preview
                            else r[cfg.col_content]
                        ),
                        "score": round(float(r["score"]), 4),
                    }
                    for r in rows
                ]
        return json.dumps(results, indent=2)
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
    cfg = ctx.config

    try:
        async with ctx.pool.acquire() as conn:
            sql = _union_select(
                cfg,
                f"{cfg.col_title}, {cfg.col_content}, {cfg.col_category}, "
                f"{cfg.col_audience}, {cfg.col_tags}, {cfg.col_chunk_index}",
                f"{cfg.col_file_path} = $1",
                f"ORDER BY {cfg.col_chunk_index} ASC",
            )
            rows = await conn.fetch(sql, path)

            if not rows:
                return json.dumps({"error": f"No document found at path: {path}"})

            first = rows[0]
            content = "\n\n".join(r[cfg.col_content] for r in rows)
            truncated = False
            if max_length and len(content) > max_length:
                content = content[:max_length] + "..."
                truncated = True

            result = {
                "title": first[cfg.col_title],
                "content": content,
                "category": first[cfg.col_category],
                "audience": first[cfg.col_audience],
                "tags": first[cfg.col_tags],
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
        async with ctx.pool.acquire() as conn:
            # Check if links table exists
            exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.links_table,
            )

            if not exists:
                return json.dumps(
                    {
                        "message": f"{cfg.qualified_links_table} table does not exist. "
                        "Related document lookup is not available.",
                        "results": [],
                    },
                    indent=2,
                )

            rows = await conn.fetch(
                f"SELECT "
                f"  CASE WHEN {cfg.col_source_path} = $1 "
                f"    THEN {cfg.col_target_path} ELSE {cfg.col_source_path} END AS related_path, "
                f"  {cfg.col_relation_type}, "
                f"  CASE WHEN {cfg.col_source_path} = $1 "
                f"    THEN 'outgoing' ELSE 'incoming' END AS direction "
                f"FROM {cfg.qualified_links_table} "
                f"WHERE {cfg.col_source_path} = $1 OR {cfg.col_target_path} = $1 "
                f"ORDER BY {cfg.col_relation_type}, related_path",
                path,
            )

            return json.dumps(
                [
                    {
                        "related_path": r["related_path"],
                        "relation_type": r["relation_type"],
                        "direction": r["direction"],
                    }
                    for r in rows
                ],
                indent=2,
            )
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

    try:
        async with ctx.pool.acquire() as conn:
            async with conn.transaction():
                # Delete existing chunks for this path
                await conn.execute(
                    f"DELETE FROM {cfg.qualified_chunks_table} "
                    f"WHERE {cfg.col_file_path} = $1",
                    path,
                )
                # Insert new chunks
                for i, chunk in enumerate(chunks):
                    await conn.execute(
                        f"INSERT INTO {cfg.qualified_chunks_table} "
                        f"({cfg.col_file_path}, {cfg.col_chunk_index}, {cfg.col_title}, "
                        f"{cfg.col_content}, {cfg.col_category}, {cfg.col_audience}, {cfg.col_tags}) "
                        f"VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        path,
                        i,
                        title,
                        chunk,
                        category,
                        audience,
                        tags,
                    )

        await _notify_webhook(ctx, "upsert", path)
        log.info("upsert_doc: path=%s chunks=%d", path, len(chunks))
        return json.dumps({"path": path, "chunks": len(chunks), "action": "upserted"})
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
        async with ctx.pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {cfg.qualified_chunks_table} "
                f"WHERE {cfg.col_file_path} = $1",
                path,
            )
            deleted = _row_count(result)

            # Also clean up links if table exists
            links_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.links_table,
            )
            links_deleted = 0
            if links_exists:
                link_result = await conn.execute(
                    f"DELETE FROM {cfg.qualified_links_table} "
                    f"WHERE {cfg.col_source_path} = $1 OR {cfg.col_target_path} = $1",
                    path,
                )
                links_deleted = _row_count(link_result)

        if deleted == 0:
            return json.dumps({"error": f"No document found at path: {path}"})

        await _notify_webhook(ctx, "delete", path)
        log.info("delete_doc: path=%s chunks=%d links=%d", path, deleted, links_deleted)
        return json.dumps(
            {
                "path": path,
                "chunks_deleted": deleted,
                "links_deleted": links_deleted,
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

    # Build SET clause dynamically for provided fields only
    updates = []
    params = [path]  # $1 = path
    idx = 2
    if title is not None:
        updates.append(f"{cfg.col_title} = ${idx}")
        params.append(title)
        idx += 1
    if category is not None:
        updates.append(f"{cfg.col_category} = ${idx}")
        params.append(category)
        idx += 1
    if audience is not None:
        updates.append(f"{cfg.col_audience} = ${idx}")
        params.append(audience)
        idx += 1
    if tags is not None:
        updates.append(f"{cfg.col_tags} = ${idx}")
        params.append(tags)
        idx += 1

    if not updates:
        return json.dumps(
            {
                "error": "No fields to update. Provide at least one of: title, category, audience, tags."
            }
        )

    try:
        async with ctx.pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE {cfg.qualified_chunks_table} "
                f"SET {', '.join(updates)} "
                f"WHERE {cfg.col_file_path} = $1",
                *params,
            )
            affected = _row_count(result)

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
    """Split content into chunks at paragraph boundaries."""
    if len(content) <= max_size:
        return [content]

    chunks = []
    paragraphs = content.split("\n\n")
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_size:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [content]
