# Gnosis MCP -- MCP Documentation Server

Open-source Python MCP server for searchable documentation. Zero-config SQLite default, PostgreSQL optional.

## Architecture

```
src/gnosis_mcp/
├── backend.py         # DocBackend Protocol + create_backend() factory
├── pg_backend.py      # PostgreSQL backend — asyncpg pool, $N params, tsvector, pgvector, UNION ALL
├── sqlite_backend.py  # SQLite backend — aiosqlite, FTS5 MATCH + bm25(), ? params
├── sqlite_schema.py   # SQLite DDL — tables, FTS5 virtual table, sync triggers, indexes
├── config.py          # GnosisMcpConfig frozen dataclass, backend auto-detection, GNOSIS_MCP_* env vars
├── db.py              # Backend lifecycle + FastMCP lifespan context manager
├── server.py          # FastMCP server: 6 tools + 3 resources + webhook helper
├── ingest.py          # File ingestion: scan markdown, chunk by H2, frontmatter, content hashing
├── schema.py          # PostgreSQL DDL — tables, indexes, HNSW, hybrid search functions
├── embed.py           # Embedding sidecar: provider abstraction (openai/ollama/custom), batch backfill
└── cli.py             # argparse CLI: serve, init-db, ingest, search, embed, stats, export, check
```

## Backend Protocol

All database operations go through `DocBackend` (a `typing.Protocol` in `backend.py`). Two implementations:

- **PostgresBackend** (`pg_backend.py`): asyncpg, `$N` params, `::vector` casts, `ts_rank`, `websearch_to_tsquery`, `<=>`, `information_schema` queries, `UNION ALL` for multi-table
- **SqliteBackend** (`sqlite_backend.py`): aiosqlite, `?` params, FTS5 `MATCH` + `bm25()`, `sqlite_master` for existence, `PRAGMA table_info` for column checks

**Auto-detection**: `DATABASE_URL` set to `postgresql://...` → PostgreSQL. Not set → SQLite at `~/.local/share/gnosis-mcp/docs.db`. Override with `GNOSIS_MCP_BACKEND=sqlite|postgres`.

## Dependencies

Default install: `mcp>=1.20` + `aiosqlite>=0.20`. Optional: `pip install gnosis-mcp[postgres]` adds `asyncpg>=0.29`.

## Tools

### Read (always available)
1. **search_docs(query, category?, limit?, query_embedding?)** -- keyword (FTS5/tsvector), hybrid (with embedding on PG), or custom function search
2. **get_doc(path, max_length?)** -- reassemble document chunks by file_path + chunk_index (optional truncation)
3. **get_related(path)** -- bidirectional link graph query

### Write (requires GNOSIS_MCP_WRITABLE=true)
4. **upsert_doc(path, content, title?, category?, audience?, tags?, embeddings?)** -- insert/replace document with auto-chunking (optional pre-computed embeddings)
5. **delete_doc(path)** -- delete document chunks + links
6. **update_metadata(path, title?, category?, audience?, tags?)** -- update metadata on all chunks

## Resources

- **gnosis://docs** -- list all documents (path, title, category, chunk count)
- **gnosis://docs/{path}** -- read document content by path
- **gnosis://categories** -- list categories with doc counts

## Key Design Decisions

- **Backend Protocol pattern**: High-level Protocol (not connection wrapper) — PG and SQLite SQL differ too much for a thin wrapper
- **FastMCP lifespan pattern**: Backend created once via `app_lifespan()`, shared across tool calls
- **SQL injection prevention**: All identifiers validated via regex in `GnosisMcpConfig.__post_init__()`
- **Multi-table support**: PostgreSQL only — `GNOSIS_MCP_CHUNKS_TABLE` accepts comma-separated tables, queries use `UNION ALL`
- **Write gating**: Write tools check `cfg.writable` and return error if disabled
- **Webhook notifications**: Fire-and-forget POST to `GNOSIS_MCP_WEBHOOK_URL` on write operations
- **Custom search delegation**: Set `GNOSIS_MCP_SEARCH_FUNCTION` to use your own hybrid search (PostgreSQL only)
- **Column overrides**: `GNOSIS_MCP_COL_*` are for connecting to existing tables with non-standard names
- **H2-based chunking**: `ingest` splits markdown by H2 headers (smarter than paragraph boundaries)
- **Content hashing**: `ingest` skips unchanged files using SHA-256 hash comparison
- **3-tier embedding support**: Accept pre-computed embeddings via tools, backfill with `gnosis-mcp embed`, built-in hybrid search when `query_embedding` is provided
- **Zero embedding deps**: Embedding providers use stdlib `urllib.request` — no new runtime dependencies
- **HNSW vector index**: PostgreSQL `init-db` creates an HNSW index for fast cosine similarity search
- **FTS5 with porter tokenizer**: SQLite uses FTS5 with porter stemming, sync triggers for INSERT/UPDATE/DELETE
- **XDG-compliant paths**: SQLite default at `~/.local/share/gnosis-mcp/docs.db`, no platformdirs dependency

## Testing

```bash
pytest tests/               # Unit tests (176 tests, no DB required)
gnosis-mcp check            # Integration check against live DB
```

## Rules

- No pydantic, no click, no ORM
- All SQL identifiers must be validated
- Pure functions should be unit-testable without a database
- Write tools must always check `cfg.writable` first
- Backend implementations use natural SQL in their own dialect — no leaky abstraction
