"""FastMCP server with 3 documentation tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ansuz.db import AppContext, app_lifespan

mcp = FastMCP("ansuz", lifespan=app_lifespan)


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
    ctx: AppContext = mcp.get_context().request_context.lifespan_context
    cfg = ctx.config
    limit = max(1, min(20, limit))

    try:
        async with ctx.pool.acquire() as conn:
            if cfg.search_function:
                # Delegate to custom search function (e.g. hybrid semantic+keyword)
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
                            r["content"][:200] + "..." if len(r["content"]) > 200 else r["content"]
                        ),
                        "score": round(float(r.get("combined_score", 0)), 4),
                    }
                    for r in rows
                ]
            else:
                # Built-in tsvector keyword search
                tbl = cfg.qualified_chunks_table
                rows = await conn.fetch(
                    f"SELECT {cfg.col_file_path}, {cfg.col_title}, {cfg.col_content}, "
                    f"{cfg.col_category}, "
                    f"ts_rank({cfg.col_tsv}, websearch_to_tsquery('english', $1)) AS score "
                    f"FROM {tbl} "
                    f"WHERE {cfg.col_tsv} @@ websearch_to_tsquery('english', $1) "
                    + (f"AND {cfg.col_category} = $3 " if category else "")
                    + f"ORDER BY score DESC LIMIT $2",
                    query,
                    limit,
                    *([category] if category else []),
                )
                results = [
                    {
                        "file_path": r[cfg.col_file_path],
                        "title": r[cfg.col_title],
                        "content_preview": (
                            r[cfg.col_content][:200] + "..."
                            if len(r[cfg.col_content]) > 200
                            else r[cfg.col_content]
                        ),
                        "score": round(float(r["score"]), 4),
                    }
                    for r in rows
                ]
        return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_doc(path: str) -> str:
    """Get full document content by file path. Reassembles all chunks in order.

    Args:
        path: Document file path (e.g. "curated/guides/design-system.md").
    """
    ctx: AppContext = mcp.get_context().request_context.lifespan_context
    cfg = ctx.config

    try:
        async with ctx.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {cfg.col_title}, {cfg.col_content}, {cfg.col_category}, "
                f"{cfg.col_audience}, {cfg.col_tags} "
                f"FROM {cfg.qualified_chunks_table} "
                f"WHERE {cfg.col_file_path} = $1 "
                f"ORDER BY {cfg.col_chunk_index} ASC",
                path,
            )

        if not rows:
            return json.dumps({"error": f"No document found at path: {path}"})

        first = rows[0]
        return json.dumps(
            {
                "title": first[cfg.col_title],
                "content": "\n\n".join(r[cfg.col_content] for r in rows),
                "category": first[cfg.col_category],
                "audience": first[cfg.col_audience],
                "tags": first[cfg.col_tags],
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_related(path: str) -> str:
    """Find documents related to a given path via incoming and outgoing links.

    Args:
        path: Document file path to find related documents for.
    """
    ctx: AppContext = mcp.get_context().request_context.lifespan_context
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

        return json.dumps([dict(r) for r in rows], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
