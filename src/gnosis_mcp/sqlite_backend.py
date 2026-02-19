"""SQLite backend using aiosqlite + FTS5 + optional sqlite-vec for hybrid search."""

from __future__ import annotations

import json
import logging
import re
import struct
from pathlib import Path
from typing import Any

__all__ = ["SqliteBackend"]

log = logging.getLogger("gnosis_mcp")

# RRF constant (standard value from the original paper)
_RRF_K = 60

# Characters that have special meaning in FTS5 queries
_FTS5_SPECIAL = re.compile(r'["\*\(\)\-\+\^:]')


def _to_fts5_query(text: str) -> str:
    """Convert natural language text to a safe FTS5 query.

    Wraps each word in quotes to prevent FTS5 syntax errors from special chars.
    Joins with implicit AND (FTS5 default).
    """
    words = text.split()
    if not words:
        return '""'
    safe = []
    for w in words:
        # Strip FTS5 special characters and quote each token
        cleaned = _FTS5_SPECIAL.sub("", w)
        if cleaned:
            safe.append(f'"{cleaned}"')
    return " ".join(safe) if safe else '""'


class SqliteBackend:
    """DocBackend implementation for SQLite with FTS5 search."""

    def __init__(self, config) -> None:
        from gnosis_mcp.config import GnosisMcpConfig

        self._cfg: GnosisMcpConfig = config
        self._db = None
        self._db_path: str = config.database_url  # For SQLite, this is the file path
        self._has_vec: bool = False

    # -- lifecycle -------------------------------------------------------------

    async def startup(self) -> None:
        import aiosqlite

        path = self._db_path
        if path == ":memory:":
            db_path = path
        else:
            db_dir = Path(path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = path

        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

        self._has_vec = await self._try_load_sqlite_vec()

        log.info(
            "gnosis-mcp started: backend=sqlite path=%s sqlite-vec=%s",
            db_path, self._has_vec,
        )

    async def _try_load_sqlite_vec(self) -> bool:
        """Attempt to load the sqlite-vec extension. Returns True on success."""
        try:
            import sqlite_vec  # noqa: F811

            await self._db.enable_load_extension(True)
            await self._db.load_extension(sqlite_vec.loadable_path())
            await self._db.enable_load_extension(False)
            return True
        except ImportError:
            log.debug("sqlite-vec not installed — vector search disabled")
            return False
        except Exception:
            log.debug("sqlite-vec extension failed to load", exc_info=True)
            return False

    async def shutdown(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # -- schema ----------------------------------------------------------------

    async def init_schema(self) -> str:
        from gnosis_mcp.sqlite_schema import get_sqlite_schema, get_vec0_schema

        statements = get_sqlite_schema()
        for stmt in statements:
            await self._db.execute(stmt)

        if self._has_vec:
            vec0_sql = get_vec0_schema(dim=self._cfg.embed_dim)
            try:
                await self._db.execute(vec0_sql)
                statements.append(vec0_sql)
            except Exception:
                log.warning("Failed to create vec0 table", exc_info=True)

        await self._db.commit()
        return "\n".join(statements)

    async def check_health(self) -> dict[str, Any]:
        result: dict[str, Any] = {"backend": "sqlite", "path": self._db_path}

        row = await self._db.execute_fetchall("SELECT sqlite_version()")
        result["version"] = f"SQLite {row[0][0]}"

        # Check chunks table
        chunks_exists = await self._table_exists("documentation_chunks")
        result["chunks_table_exists"] = chunks_exists
        if chunks_exists:
            row = await self._db.execute_fetchall(
                "SELECT count(*) FROM documentation_chunks"
            )
            result["chunks_count"] = row[0][0]

        # Check FTS table
        fts_exists = await self._table_exists("documentation_chunks_fts")
        result["fts_table_exists"] = fts_exists

        # sqlite-vec status
        result["sqlite_vec"] = self._has_vec
        if self._has_vec:
            vec_exists = await self._table_exists("documentation_chunks_vec")
            result["vec_table_exists"] = vec_exists
            if vec_exists:
                row = await self._db.execute_fetchall(
                    "SELECT count(*) FROM documentation_chunks_vec"
                )
                result["vec_count"] = row[0][0]

        # Check links table
        links_exists = await self._table_exists("documentation_links")
        result["links_table_exists"] = links_exists
        if links_exists:
            row = await self._db.execute_fetchall(
                "SELECT count(*) FROM documentation_links"
            )
            result["links_count"] = row[0][0]

        return result

    async def _table_exists(self, name: str) -> bool:
        rows = await self._db.execute_fetchall(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return len(rows) > 0

    # -- search ----------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if query_embedding and self._has_vec and await self._table_exists(
            "documentation_chunks_vec"
        ):
            return await self._search_hybrid(
                query, query_embedding, category=category, limit=limit
            )
        return await self._search_keyword(query, category=category, limit=limit)

    async def _search_keyword(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """FTS5 keyword-only search (existing path)."""
        fts_query = _to_fts5_query(query)

        sql = (
            "SELECT c.file_path, c.title, c.content, c.category, "
            "  bm25(documentation_chunks_fts) AS score "
            "FROM documentation_chunks_fts f "
            "JOIN documentation_chunks c ON c.id = f.rowid "
            "WHERE documentation_chunks_fts MATCH ? "
        )
        params: list[Any] = [fts_query]

        if category:
            sql += "AND c.category = ? "
            params.append(category)

        # bm25 returns negative values (lower = better match), so ORDER BY ASC
        sql += "ORDER BY score ASC LIMIT ?"
        params.append(limit)

        rows = await self._db.execute_fetchall(sql, params)
        return [
            {
                "file_path": r[0],
                "title": r[1],
                "content": r[2],
                "category": r[3],
                "score": -float(r[4]),  # Negate to make higher = better
            }
            for r in rows
        ]

    async def _search_hybrid(
        self,
        query: str,
        query_embedding: list[float],
        *,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Hybrid search: FTS5 keyword + sqlite-vec semantic, merged with RRF."""
        import sqlite_vec

        # Fetch more candidates than needed for RRF merging
        fetch_n = max(limit * 4, 20)

        # 1. Keyword results (FTS5 BM25)
        keyword_results = await self._search_keyword(
            query, category=category, limit=fetch_n
        )

        # 2. Semantic results (sqlite-vec KNN cosine distance)
        query_blob = sqlite_vec.serialize_float32(query_embedding)
        vec_sql = (
            "SELECT v.chunk_id, v.distance "
            "FROM documentation_chunks_vec v "
            "WHERE v.embedding MATCH ? "
            "ORDER BY v.distance ASC "
            "LIMIT ?"
        )
        vec_rows = await self._db.execute_fetchall(vec_sql, (query_blob, fetch_n))

        # Build lookup: chunk_id → row data
        semantic_ids = [r[0] for r in vec_rows]
        semantic_map: dict[int, float] = {}  # chunk_id → distance
        for r in vec_rows:
            semantic_map[r[0]] = float(r[1])

        # Fetch full chunk data for semantic results
        chunk_data: dict[int, dict[str, Any]] = {}
        if semantic_ids:
            placeholders = ",".join("?" * len(semantic_ids))
            data_sql = (
                f"SELECT id, file_path, title, content, category "
                f"FROM documentation_chunks WHERE id IN ({placeholders})"
            )
            data_rows = await self._db.execute_fetchall(data_sql, semantic_ids)
            for r in data_rows:
                chunk_data[r[0]] = {
                    "file_path": r[1],
                    "title": r[2],
                    "content": r[3],
                    "category": r[4],
                }

        # Apply category filter to semantic results if needed
        if category:
            semantic_ids = [
                cid for cid in semantic_ids
                if cid in chunk_data and chunk_data[cid]["category"] == category
            ]

        # 3. RRF merge
        # Build rank maps (1-indexed)
        keyword_rank: dict[str, int] = {}
        keyword_data: dict[str, dict[str, Any]] = {}
        for rank, r in enumerate(keyword_results, 1):
            fp_key = f"{r['file_path']}:{r['content'][:50]}"
            keyword_rank[fp_key] = rank
            keyword_data[fp_key] = r

        semantic_rank: dict[str, int] = {}
        semantic_data_by_key: dict[str, dict[str, Any]] = {}
        for rank, cid in enumerate(semantic_ids, 1):
            if cid not in chunk_data:
                continue
            cd = chunk_data[cid]
            fp_key = f"{cd['file_path']}:{cd['content'][:50]}"
            semantic_rank[fp_key] = rank
            semantic_data_by_key[fp_key] = cd

        # Compute RRF scores
        all_keys = set(keyword_rank) | set(semantic_rank)
        rrf_scores: list[tuple[float, str]] = []
        for key in all_keys:
            score = 0.0
            if key in keyword_rank:
                score += 1.0 / (_RRF_K + keyword_rank[key])
            if key in semantic_rank:
                score += 1.0 / (_RRF_K + semantic_rank[key])
            rrf_scores.append((score, key))

        rrf_scores.sort(reverse=True)

        # Build final results
        results: list[dict[str, Any]] = []
        for score, key in rrf_scores[:limit]:
            if key in keyword_data:
                data = keyword_data[key]
            elif key in semantic_data_by_key:
                data = semantic_data_by_key[key]
            else:
                continue
            results.append({
                "file_path": data["file_path"],
                "title": data["title"],
                "content": data["content"],
                "category": data["category"],
                "score": score,
            })

        return results

    # -- document CRUD ---------------------------------------------------------

    async def get_doc(self, path: str) -> list[dict[str, Any]]:
        rows = await self._db.execute_fetchall(
            "SELECT title, content, category, audience, tags, chunk_index "
            "FROM documentation_chunks WHERE file_path = ? "
            "ORDER BY chunk_index ASC",
            (path,),
        )
        return [
            {
                "title": r[0],
                "content": r[1],
                "category": r[2],
                "audience": r[3],
                "tags": json.loads(r[4]) if r[4] else None,
                "chunk_index": r[5],
            }
            for r in rows
        ]

    async def get_related(self, path: str) -> list[dict[str, Any]] | None:
        if not await self._table_exists("documentation_links"):
            return None

        rows = await self._db.execute_fetchall(
            "SELECT "
            "  CASE WHEN source_path = ? THEN target_path ELSE source_path END AS related_path, "
            "  relation_type, "
            "  CASE WHEN source_path = ? THEN 'outgoing' ELSE 'incoming' END AS direction "
            "FROM documentation_links "
            "WHERE source_path = ? OR target_path = ? "
            "ORDER BY relation_type, related_path",
            (path, path, path, path),
        )
        return [
            {
                "related_path": r[0],
                "relation_type": r[1],
                "direction": r[2],
            }
            for r in rows
        ]

    async def list_docs(self) -> list[dict[str, Any]]:
        rows = await self._db.execute_fetchall(
            "SELECT file_path, MIN(title) AS title, MIN(category) AS category, "
            "  COUNT(*) AS chunks "
            "FROM documentation_chunks "
            "GROUP BY file_path "
            "ORDER BY category, file_path"
        )
        return [
            {
                "file_path": r[0],
                "title": r[1],
                "category": r[2],
                "chunks": r[3],
            }
            for r in rows
        ]

    async def list_categories(self) -> list[dict[str, Any]]:
        rows = await self._db.execute_fetchall(
            "SELECT category, COUNT(DISTINCT file_path) AS docs "
            "FROM documentation_chunks "
            "WHERE category IS NOT NULL "
            "GROUP BY category "
            "ORDER BY category"
        )
        return [{"category": r[0], "docs": r[1]} for r in rows]

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
        tags_json = json.dumps(tags) if tags else None

        await self._db.execute(
            "DELETE FROM documentation_chunks WHERE file_path = ?", (path,)
        )
        for i, chunk in enumerate(chunks):
            await self._db.execute(
                "INSERT INTO documentation_chunks "
                "(file_path, chunk_index, title, content, category, audience, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, i, title, chunk, category, audience, tags_json),
            )
        await self._db.commit()
        return len(chunks)

    async def delete_doc(self, path: str) -> dict[str, int]:
        cursor = await self._db.execute(
            "DELETE FROM documentation_chunks WHERE file_path = ?", (path,)
        )
        chunks_deleted = cursor.rowcount

        links_deleted = 0
        if await self._table_exists("documentation_links"):
            cursor = await self._db.execute(
                "DELETE FROM documentation_links "
                "WHERE source_path = ? OR target_path = ?",
                (path, path),
            )
            links_deleted = cursor.rowcount

        await self._db.commit()
        return {"chunks_deleted": chunks_deleted, "links_deleted": links_deleted}

    async def update_metadata(
        self,
        path: str,
        *,
        title: str | None = None,
        category: str | None = None,
        audience: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        updates = []
        params: list[Any] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if audience is not None:
            updates.append("audience = ?")
            params.append(audience)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))

        if not updates:
            return 0

        params.append(path)
        cursor = await self._db.execute(
            f"UPDATE documentation_chunks SET {', '.join(updates)} WHERE file_path = ?",
            params,
        )
        await self._db.commit()
        return cursor.rowcount

    # -- stats / export --------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        rows = await self._db.execute_fetchall(
            "SELECT count(*) FROM documentation_chunks"
        )
        total = rows[0][0]

        rows = await self._db.execute_fetchall(
            "SELECT count(DISTINCT file_path) FROM documentation_chunks"
        )
        docs = rows[0][0]

        cats = await self._db.execute_fetchall(
            "SELECT category AS cat, count(DISTINCT file_path) AS docs, "
            "count(*) AS chunks "
            "FROM documentation_chunks GROUP BY category ORDER BY docs DESC"
        )

        rows = await self._db.execute_fetchall(
            "SELECT coalesce(sum(length(content)), 0) FROM documentation_chunks"
        )
        size = rows[0][0]

        links = None
        if await self._table_exists("documentation_links"):
            rows = await self._db.execute_fetchall(
                "SELECT count(*) FROM documentation_links"
            )
            links = rows[0][0]

        # Embedded chunks count
        rows = await self._db.execute_fetchall(
            "SELECT count(*) FROM documentation_chunks WHERE embedding IS NOT NULL"
        )
        embedded = rows[0][0]

        result = {
            "table": "documentation_chunks",
            "docs": docs,
            "chunks": total,
            "embedded_chunks": embedded,
            "content_bytes": size,
            "categories": [
                {"cat": r[0], "docs": r[1], "chunks": r[2]} for r in cats
            ],
            "links": links,
            "sqlite_vec": self._has_vec,
        }

        return result

    async def export_docs(self, category: str | None = None) -> list[dict[str, Any]]:
        if category:
            rows = await self._db.execute_fetchall(
                "SELECT file_path, chunk_index, title, content, category "
                "FROM documentation_chunks WHERE category = ? "
                "ORDER BY file_path, chunk_index",
                (category,),
            )
        else:
            rows = await self._db.execute_fetchall(
                "SELECT file_path, chunk_index, title, content, category "
                "FROM documentation_chunks ORDER BY file_path, chunk_index"
            )

        docs: dict[str, dict] = {}
        for r in rows:
            fp = r[0]
            if fp not in docs:
                docs[fp] = {
                    "file_path": fp,
                    "title": r[2],
                    "category": r[4],
                    "content": "",
                }
            docs[fp]["content"] += r[3] + "\n\n"

        for d in docs.values():
            d["content"] = d["content"].rstrip()

        return list(docs.values())

    # -- embedding support -----------------------------------------------------

    async def count_pending_embeddings(self) -> int:
        rows = await self._db.execute_fetchall(
            "SELECT count(*) FROM documentation_chunks WHERE embedding IS NULL"
        )
        return rows[0][0]

    async def get_pending_embeddings(self, batch_size: int) -> list[dict[str, Any]]:
        rows = await self._db.execute_fetchall(
            "SELECT id, content FROM documentation_chunks "
            "WHERE embedding IS NULL ORDER BY id LIMIT ?",
            (batch_size,),
        )
        return [{"id": r[0], "content": r[1]} for r in rows]

    async def set_embedding(self, chunk_id: int, embedding: list[float]) -> None:
        # Store as binary blob (compact float32 array)
        blob = struct.pack(f"<{len(embedding)}f", *embedding)
        await self._db.execute(
            "UPDATE documentation_chunks SET embedding = ? WHERE id = ?",
            (blob, chunk_id),
        )

        # Also write to vec0 table for KNN search
        if self._has_vec and await self._table_exists("documentation_chunks_vec"):
            try:
                import sqlite_vec

                vec_blob = sqlite_vec.serialize_float32(embedding)
                await self._db.execute(
                    "INSERT OR REPLACE INTO documentation_chunks_vec(chunk_id, embedding) "
                    "VALUES (?, ?)",
                    (chunk_id, vec_blob),
                )
            except Exception:
                log.debug("Failed to write vec0 embedding for chunk %d", chunk_id)

        await self._db.commit()

    # -- ingest support --------------------------------------------------------

    async def has_column(self, table: str, column: str) -> bool:
        rows = await self._db.execute_fetchall(
            f"PRAGMA table_info({table})"
        )
        return any(r[1] == column for r in rows)

    async def get_content_hash(self, path: str) -> str | None:
        rows = await self._db.execute_fetchall(
            "SELECT content_hash FROM documentation_chunks "
            "WHERE file_path = ? LIMIT 1",
            (path,),
        )
        return rows[0][0] if rows else None

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
        tags_json = json.dumps(tags) if tags else None

        await self._db.execute(
            "DELETE FROM documentation_chunks WHERE file_path = ?", (rel_path,)
        )
        for i, chunk in enumerate(chunks):
            cols = "file_path, chunk_index, title, content, category, audience"
            vals = "?, ?, ?, ?, ?, ?"
            params: list[Any] = [
                rel_path, i, chunk["title"], chunk["content"],
                category, audience,
            ]

            if has_tags_col and tags_json:
                cols += ", tags"
                vals += ", ?"
                params.append(tags_json)

            if has_hash_col and content_hash:
                cols += ", content_hash"
                vals += ", ?"
                params.append(content_hash)

            await self._db.execute(
                f"INSERT INTO documentation_chunks ({cols}) VALUES ({vals})",
                params,
            )
        await self._db.commit()
        return len(chunks)
