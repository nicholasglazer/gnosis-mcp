"""PostgreSQL backend using asyncpg."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["PostgresBackend"]

log = logging.getLogger("gnosis_mcp")


def _to_or_query(text: str) -> str:
    """Convert multi-word query to websearch_to_tsquery OR format.

    'payment docker' → 'payment or docker'
    websearch_to_tsquery treats bare 'or' as the OR operator.
    """
    words = text.split()
    if len(words) <= 1:
        return text
    return " or ".join(words)


def _row_count(status: str) -> int:
    """Extract row count from asyncpg status string (e.g. 'DELETE 5' -> 5)."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


class PostgresBackend:
    """DocBackend implementation for PostgreSQL with pgvector."""

    def __init__(self, config) -> None:
        from gnosis_mcp.config import GnosisMcpConfig

        self._cfg: GnosisMcpConfig = config
        self._pool = None

    # -- lifecycle -------------------------------------------------------------

    async def startup(self) -> None:
        import asyncpg

        cfg = self._cfg
        try:
            self._pool = await asyncpg.create_pool(
                cfg.database_url,
                min_size=cfg.pool_min,
                max_size=cfg.pool_max,
            )
        except (OSError, asyncpg.PostgresError) as exc:
            log.error("Failed to connect to database: %s", exc)
            log.error("Check GNOSIS_MCP_DATABASE_URL and ensure PostgreSQL is running")
            raise SystemExit(1) from exc

        async with self._pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

        log.info(
            "gnosis-mcp started: backend=postgres schema=%s chunks=%s links=%s search_fn=%s",
            cfg.schema,
            cfg.chunks_table,
            cfg.links_table,
            cfg.search_function or "(built-in tsvector)",
        )

    async def shutdown(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # -- helpers ---------------------------------------------------------------

    def _union_select(self, select_clause: str, where_clause: str = "", order_clause: str = "") -> str:
        cfg = self._cfg
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

    async def _acquire(self):
        """Acquire a connection from the pool, or create a standalone connection."""
        if self._pool:
            return self._pool.acquire()
        # Standalone connection for CLI commands
        class _StandaloneCtx:
            def __init__(self, url):
                self._url = url
                self._conn = None

            async def __aenter__(self):
                import asyncpg as apg
                self._conn = await apg.connect(self._url)
                return self._conn

            async def __aexit__(self, *exc):
                if self._conn:
                    await self._conn.close()

        return _StandaloneCtx(self._cfg.database_url)

    # -- schema ----------------------------------------------------------------

    async def init_schema(self) -> str:
        import asyncpg

        from gnosis_mcp.schema import get_init_sql

        sql = get_init_sql(self._cfg)
        conn = await asyncpg.connect(self._cfg.database_url)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()
        return sql

    async def check_health(self) -> dict[str, Any]:
        import asyncpg

        cfg = self._cfg
        result: dict[str, Any] = {"backend": "postgres"}
        conn = await asyncpg.connect(cfg.database_url)
        try:
            version = await conn.fetchval("SELECT version()")
            result["version"] = version.split(",")[0]

            has_vector = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            result["pgvector"] = has_vector

            chunks_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.chunks_tables[0],
            )
            result["chunks_table_exists"] = chunks_exists
            if chunks_exists:
                count = await conn.fetchval(
                    f"SELECT count(*) FROM {cfg.qualified_chunks_table}"
                )
                result["chunks_count"] = count

            links_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.links_table,
            )
            result["links_table_exists"] = links_exists
            if links_exists:
                count = await conn.fetchval(
                    f"SELECT count(*) FROM {cfg.qualified_links_table}"
                )
                result["links_count"] = count

            if cfg.search_function:
                fn_schema, fn_name = (
                    cfg.search_function.split(".", 1)
                    if "." in cfg.search_function
                    else ("public", cfg.search_function)
                )
                fn_exists = await conn.fetchval(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.routines"
                    "  WHERE routine_schema = $1 AND routine_name = $2"
                    ")",
                    fn_schema,
                    fn_name,
                )
                result["search_function_exists"] = fn_exists
        finally:
            await conn.close()
        return result

    # -- search ----------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        cfg = self._cfg

        or_query = _to_or_query(query)
        async with await self._acquire() as conn:
            if cfg.search_function:
                # Pass raw query — custom functions do their own query parsing.
                # _to_or_query breaks custom functions' ILIKE fallback and
                # causes websearch_to_tsquery to treat "or" as boolean OR.
                return await self._search_custom(conn, query, category, limit, query_embedding)
            elif query_embedding:
                return await self._search_hybrid(conn, or_query, category, limit, query_embedding)
            else:
                return await self._search_keyword(conn, or_query, category, limit)

    async def _search_custom(self, conn, query, category, limit, query_embedding):
        cfg = self._cfg
        if query_embedding:
            embedding_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
            try:
                rows = await conn.fetch(
                    f"SELECT * FROM {cfg.search_function}("
                    f"p_query_text := $1, p_embedding := $2::vector, "
                    f"p_categories := $3, p_limit := $4)",
                    query,
                    embedding_str,
                    [category] if category else None,
                    limit,
                )
            except Exception:
                log.debug("Custom search function doesn't accept p_embedding, falling back")
                rows = await conn.fetch(
                    f"SELECT * FROM {cfg.search_function}("
                    f"p_query_text := $1, p_categories := $2, p_limit := $3)",
                    query,
                    [category] if category else None,
                    limit,
                )
        else:
            rows = await conn.fetch(
                f"SELECT * FROM {cfg.search_function}("
                f"p_query_text := $1, p_categories := $2, p_limit := $3)",
                query,
                [category] if category else None,
                limit,
            )
        return [
            {
                "file_path": r["file_path"],
                "title": r["title"],
                "content": r["content"],
                "category": r.get("category"),
                "score": float(r.get("combined_score", 0)),
                "highlight": r.get("highlight"),
            }
            for r in rows
        ]

    async def _search_hybrid(self, conn, query, category, limit, query_embedding):
        cfg = self._cfg
        embedding_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
        # Always use $3 for embedding, $4 for category (when present).
        # This avoids parameter numbering gaps when category is None.
        select = (
            f"{cfg.col_file_path}, {cfg.col_title}, {cfg.col_content}, "
            f"{cfg.col_category}, "
            f"CASE WHEN {cfg.col_embedding} IS NOT NULL THEN "
            f"  (ts_rank({cfg.col_tsv}, websearch_to_tsquery('english', $1))::float * 0.4 "
            f"  + (1.0 - ({cfg.col_embedding} <=> $3::vector))::float * 0.6) "
            f"ELSE ts_rank({cfg.col_tsv}, websearch_to_tsquery('english', $1))::float "
            f"END AS score, "
            f"ts_headline('english', {cfg.col_content}, websearch_to_tsquery('english', $1), "
            f"'StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=20') AS highlight"
        )
        where = (
            f"({cfg.col_tsv} @@ websearch_to_tsquery('english', $1) "
            f"OR ({cfg.col_embedding} IS NOT NULL "
            f"AND ({cfg.col_embedding} <=> $3::vector) < 0.8))"
        )
        if category:
            where += f" AND {cfg.col_category} = $4"
        sql = self._union_select(select, where, "ORDER BY score DESC LIMIT $2")
        params = [query, limit, embedding_str]
        if category:
            params.append(category)
        rows = await conn.fetch(sql, *params)
        return [
            {
                "file_path": r[cfg.col_file_path],
                "title": r[cfg.col_title],
                "content": r[cfg.col_content],
                "category": r.get(cfg.col_category),
                "score": float(r["score"]),
                "highlight": r["highlight"],
            }
            for r in rows
        ]

    async def _search_keyword(self, conn, query, category, limit):
        cfg = self._cfg
        select = (
            f"{cfg.col_file_path}, {cfg.col_title}, {cfg.col_content}, "
            f"{cfg.col_category}, "
            f"ts_rank({cfg.col_tsv}, websearch_to_tsquery('english', $1)) AS score, "
            f"ts_headline('english', {cfg.col_content}, websearch_to_tsquery('english', $1), "
            f"'StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=20') AS highlight"
        )
        where = f"{cfg.col_tsv} @@ websearch_to_tsquery('english', $1)"
        if category:
            where += f" AND {cfg.col_category} = $3"
        sql = self._union_select(select, where, "ORDER BY score DESC LIMIT $2")
        rows = await conn.fetch(
            sql,
            query,
            limit,
            *([category] if category else []),
        )
        return [
            {
                "file_path": r[cfg.col_file_path],
                "title": r[cfg.col_title],
                "content": r[cfg.col_content],
                "category": r.get(cfg.col_category),
                "score": float(r["score"]),
                "highlight": r["highlight"],
            }
            for r in rows
        ]

    # -- document CRUD ---------------------------------------------------------

    async def get_doc(self, path: str) -> list[dict[str, Any]]:
        cfg = self._cfg
        async with await self._acquire() as conn:
            sql = self._union_select(
                f"{cfg.col_title}, {cfg.col_content}, {cfg.col_category}, "
                f"{cfg.col_audience}, {cfg.col_tags}, {cfg.col_chunk_index}",
                f"{cfg.col_file_path} = $1",
                f"ORDER BY {cfg.col_chunk_index} ASC",
            )
            rows = await conn.fetch(sql, path)
            return [
                {
                    "title": r[cfg.col_title],
                    "content": r[cfg.col_content],
                    "category": r[cfg.col_category],
                    "audience": r[cfg.col_audience],
                    "tags": r[cfg.col_tags],
                    "chunk_index": r[cfg.col_chunk_index],
                }
                for r in rows
            ]

    async def get_related(self, path: str) -> list[dict[str, Any]] | None:
        cfg = self._cfg
        async with await self._acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.links_table,
            )
            if not exists:
                return None

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
            return [
                {
                    "related_path": r["related_path"],
                    "relation_type": r[cfg.col_relation_type],
                    "direction": r["direction"],
                }
                for r in rows
            ]

    async def list_docs(self) -> list[dict[str, Any]]:
        cfg = self._cfg
        async with await self._acquire() as conn:
            inner = self._union_select(
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
            return [
                {
                    "file_path": r[cfg.col_file_path],
                    "title": r["title"],
                    "category": r["category"],
                    "chunks": r["chunks"],
                }
                for r in rows
            ]

    async def list_categories(self) -> list[dict[str, Any]]:
        cfg = self._cfg
        async with await self._acquire() as conn:
            inner = self._union_select(
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
            return [{"category": r["category"], "docs": r["docs"]} for r in rows]

    async def upsert_doc(
        self,
        path: str,
        chunks: list[str],
        *,
        title: str | None = None,
        category: str | None = None,
        audience: str = "all",
        tags: list[str] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> int:
        cfg = self._cfg
        async with await self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"DELETE FROM {cfg.qualified_chunks_table} "
                    f"WHERE {cfg.col_file_path} = $1",
                    path,
                )
                for i, chunk in enumerate(chunks):
                    if embeddings is not None:
                        embedding_str = "[" + ",".join(str(f) for f in embeddings[i]) + "]"
                        await conn.execute(
                            f"INSERT INTO {cfg.qualified_chunks_table} "
                            f"({cfg.col_file_path}, {cfg.col_chunk_index}, {cfg.col_title}, "
                            f"{cfg.col_content}, {cfg.col_category}, {cfg.col_audience}, "
                            f"{cfg.col_tags}, {cfg.col_embedding}) "
                            f"VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)",
                            path, i, title, chunk, category, audience, tags, embedding_str,
                        )
                    else:
                        await conn.execute(
                            f"INSERT INTO {cfg.qualified_chunks_table} "
                            f"({cfg.col_file_path}, {cfg.col_chunk_index}, {cfg.col_title}, "
                            f"{cfg.col_content}, {cfg.col_category}, {cfg.col_audience}, {cfg.col_tags}) "
                            f"VALUES ($1, $2, $3, $4, $5, $6, $7)",
                            path, i, title, chunk, category, audience, tags,
                        )
        return len(chunks)

    async def delete_doc(self, path: str) -> dict[str, int]:
        cfg = self._cfg
        async with await self._acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {cfg.qualified_chunks_table} "
                f"WHERE {cfg.col_file_path} = $1",
                path,
            )
            deleted = _row_count(result)

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

        return {"chunks_deleted": deleted, "links_deleted": links_deleted}

    async def update_metadata(
        self,
        path: str,
        *,
        title: str | None = None,
        category: str | None = None,
        audience: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        cfg = self._cfg
        updates = []
        params: list[Any] = [path]
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
            return 0

        async with await self._acquire() as conn:
            result = await conn.execute(
                f"UPDATE {cfg.qualified_chunks_table} "
                f"SET {', '.join(updates)} "
                f"WHERE {cfg.col_file_path} = $1",
                *params,
            )
            return _row_count(result)

    # -- stats / export --------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        async with await self._acquire() as conn:
            total = await conn.fetchval(f"SELECT count(*) FROM {qt}")
            docs = await conn.fetchval(
                f"SELECT count(DISTINCT {cfg.col_file_path}) FROM {qt}"
            )
            cats = await conn.fetch(
                f"SELECT {cfg.col_category} AS cat, count(DISTINCT {cfg.col_file_path}) AS docs, "
                f"count(*) AS chunks "
                f"FROM {qt} GROUP BY {cfg.col_category} ORDER BY docs DESC"
            )
            size = await conn.fetchval(
                f"SELECT coalesce(sum(length({cfg.col_content})), 0) FROM {qt}"
            )

            links = None
            links_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = $1 AND table_name = $2"
                ")",
                cfg.schema,
                cfg.links_table,
            )
            if links_exists:
                links = await conn.fetchval(
                    f"SELECT count(*) FROM {cfg.qualified_links_table}"
                )

        return {
            "table": qt,
            "docs": docs,
            "chunks": total,
            "content_bytes": size,
            "categories": [
                {"cat": r["cat"], "docs": r["docs"], "chunks": r["chunks"]}
                for r in cats
            ],
            "links": links,
        }

    async def export_docs(self, category: str | None = None) -> list[dict[str, Any]]:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        async with await self._acquire() as conn:
            where = ""
            params: list[Any] = []
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

        for d in docs.values():
            d["content"] = d["content"].rstrip()

        return list(docs.values())

    # -- embedding support -----------------------------------------------------

    async def count_pending_embeddings(self) -> int:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        async with await self._acquire() as conn:
            return await conn.fetchval(
                f"SELECT count(*) FROM {qt} WHERE {cfg.col_embedding} IS NULL"
            )

    async def get_pending_embeddings(self, batch_size: int) -> list[dict[str, Any]]:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        async with await self._acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, {cfg.col_content} FROM {qt} "
                f"WHERE {cfg.col_embedding} IS NULL "
                f"ORDER BY id LIMIT $1",
                batch_size,
            )
            return [{"id": r["id"], "content": r[cfg.col_content]} for r in rows]

    async def set_embedding(self, chunk_id: int, embedding: list[float]) -> None:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        embedding_str = "[" + ",".join(str(f) for f in embedding) + "]"
        async with await self._acquire() as conn:
            await conn.execute(
                f"UPDATE {qt} SET {cfg.col_embedding} = $1::vector WHERE id = $2",
                embedding_str,
                chunk_id,
            )

    # -- ingest support --------------------------------------------------------

    async def has_column(self, table: str, column: str) -> bool:
        cfg = self._cfg
        async with await self._acquire() as conn:
            return await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.columns"
                "  WHERE table_schema = $1 AND table_name = $2 AND column_name = $3"
                ")",
                cfg.schema,
                table,
                column,
            )

    async def get_content_hash(self, path: str) -> str | None:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        async with await self._acquire() as conn:
            return await conn.fetchval(
                f"SELECT content_hash FROM {qt} WHERE file_path = $1 LIMIT 1",
                path,
            )

    async def insert_links(
        self,
        source_path: str,
        target_paths: list[str],
        relation_type: str = "relates_to",
    ) -> int:
        if not target_paths:
            return 0
        cfg = self._cfg
        lt = cfg.qualified_links_table

        async with await self._acquire() as conn:
            await conn.execute(
                f"DELETE FROM {lt} "
                f"WHERE {cfg.col_source_path} = $1 AND {cfg.col_relation_type} = $2",
                source_path,
                relation_type,
            )

            count = 0
            for target in target_paths:
                await conn.execute(
                    f"INSERT INTO {lt} ({cfg.col_source_path}, {cfg.col_target_path}, {cfg.col_relation_type}) "
                    f"VALUES ($1, $2, $3) "
                    f"ON CONFLICT ({cfg.col_source_path}, {cfg.col_target_path}, {cfg.col_relation_type}) DO NOTHING",
                    source_path,
                    target,
                    relation_type,
                )
                count += 1

            return count

    async def ingest_file(
        self,
        rel_path: str,
        chunks: list[dict[str, str]],
        *,
        title: str,
        category: str,
        audience: str,
        tags: list[str] | None = None,
        content_hash: str | None = None,
        has_tags_col: bool = True,
        has_hash_col: bool = False,
    ) -> int:
        cfg = self._cfg
        qt = cfg.qualified_chunks_table
        async with await self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"DELETE FROM {qt} WHERE file_path = $1", rel_path
                )
                for i, chunk in enumerate(chunks):
                    cols = "file_path, chunk_index, title, content, category, audience"
                    vals = "$1, $2, $3, $4, $5, $6"
                    params: list[Any] = [
                        rel_path, i, chunk["title"], chunk["content"],
                        category, audience,
                    ]
                    idx = 7

                    if has_tags_col and tags:
                        cols += ", tags"
                        vals += f", ${idx}"
                        params.append(tags)
                        idx += 1

                    if has_hash_col and content_hash:
                        cols += ", content_hash"
                        vals += f", ${idx}"
                        params.append(content_hash)
                        idx += 1

                    await conn.execute(
                        f"INSERT INTO {qt} ({cols}) VALUES ({vals})",
                        *params,
                    )
        return len(chunks)
