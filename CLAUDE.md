# Gnosis MCP -- MCP Documentation Server

Open-source Python MCP server for searchable documentation. Zero-config SQLite default, PostgreSQL optional.

## Architecture

```
src/gnosis_mcp/
├── backend.py         # DocBackend Protocol + create_backend() factory
├── pg_backend.py      # PostgreSQL backend — asyncpg pool, $N params, tsvector, pgvector, UNION ALL
├── sqlite_backend.py  # SQLite backend — aiosqlite, FTS5 + sqlite-vec hybrid (RRF), ? params
├── sqlite_schema.py   # SQLite DDL — tables, FTS5 virtual table, vec0 virtual table, sync triggers
├── config.py          # GnosisMcpConfig frozen dataclass, backend auto-detection, GNOSIS_MCP_* env vars
├── db.py              # Backend lifecycle + FastMCP lifespan context manager
├── server.py          # FastMCP server: 6 tools + 3 resources + auto-embed queries
├── ingest.py          # File ingestion + converters: multi-format (.md/.txt/.ipynb/.toml/.csv/.json), smart chunking, hashing
├── watch.py           # File watcher: mtime polling, debounce, auto-re-ingest + auto-embed on changes
├── schema.py          # PostgreSQL DDL — tables, indexes, HNSW, hybrid search functions
├── embed.py           # Embedding providers: openai/ollama/custom/local, batch backfill
├── local_embed.py     # Local ONNX embedding engine — stdlib urllib model download, CPU inference
└── cli.py             # argparse CLI: serve, init-db, ingest, search, embed, stats, export, diff, check
```

## Backend Protocol

All database operations go through `DocBackend` (a `typing.Protocol` in `backend.py`). Two implementations:

- **PostgresBackend** (`pg_backend.py`): asyncpg, `$N` params, `::vector` casts, `ts_rank`, `websearch_to_tsquery`, `<=>`, `information_schema` queries, `UNION ALL` for multi-table
- **SqliteBackend** (`sqlite_backend.py`): aiosqlite, `?` params, FTS5 `MATCH` + `bm25()`, sqlite-vec for hybrid search (RRF), `sqlite_master` for existence, `PRAGMA table_info` for column checks

**Auto-detection**: `DATABASE_URL` set to `postgresql://...` → PostgreSQL. Not set → SQLite at `~/.local/share/gnosis-mcp/docs.db`. Override with `GNOSIS_MCP_BACKEND=sqlite|postgres`.

## Dependencies

Default install: `mcp>=1.20` + `aiosqlite>=0.20`. Optional: `pip install gnosis-mcp[postgres]` adds `asyncpg>=0.29`. Optional: `pip install gnosis-mcp[embeddings]` adds `onnxruntime`, `tokenizers`, `numpy`, `sqlite-vec`. Model download uses stdlib `urllib` (no `huggingface-hub` dependency).

## Tools

### Read (always available)
1. **search_docs(query, category?, limit?, query_embedding?)** -- keyword (FTS5/tsvector), hybrid (with embedding on SQLite via sqlite-vec or PG via pgvector), or custom function search. Auto-embeds query when local provider configured.
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
- **Streamable HTTP transport**: `gnosis-mcp serve --transport streamable-http` exposes `/mcp` endpoint via uvicorn. Supports remote deployment. Configure with `--host` / `--port` or `GNOSIS_MCP_HOST` / `GNOSIS_MCP_PORT`
- **SQL injection prevention**: All identifiers validated via regex in `GnosisMcpConfig.__post_init__()`
- **Multi-table support**: PostgreSQL only — `GNOSIS_MCP_CHUNKS_TABLE` accepts comma-separated tables, queries use `UNION ALL`
- **Write gating**: Write tools check `cfg.writable` and return error if disabled
- **Webhook notifications**: Fire-and-forget POST to `GNOSIS_MCP_WEBHOOK_URL` on write operations
- **Custom search delegation**: Set `GNOSIS_MCP_SEARCH_FUNCTION` to use your own hybrid search (PostgreSQL only)
- **Column overrides**: `GNOSIS_MCP_COL_*` are for connecting to existing tables with non-standard names
- **Frontmatter link extraction**: `ingest` parses `relates_to` from frontmatter (comma-separated or YAML list), inserts into links table for `get_related` queries. Glob patterns are skipped.
- **Smart recursive chunking**: `ingest` splits by H2 (primary), H3/H4 (for oversized sections), then paragraphs. Never splits inside fenced code blocks or tables
- **Content hashing**: `ingest` skips unchanged files using SHA-256 hash comparison
- **4-tier embedding support**: (1) Local ONNX via `[embeddings]` extra, (2) pre-computed embeddings via tools, (3) backfill with `gnosis-mcp embed`, (4) built-in hybrid search when `query_embedding` is provided
- **Local ONNX embedder**: `local_embed.py` — HuggingFace model auto-download, ONNX Runtime CPU inference, mean pooling, L2 normalization, Matryoshka dimension truncation
- **sqlite-vec hybrid search**: Reciprocal Rank Fusion (RRF) merges FTS5 keyword + vec0 cosine results. Better than linear blending for incompatible score scales.
- **Zero embedding deps for remote providers**: Remote providers use stdlib `urllib.request` — no new runtime dependencies
- **HNSW vector index**: PostgreSQL `init-db` creates an HNSW index for fast cosine similarity search
- **FTS5 with porter tokenizer**: SQLite uses FTS5 with porter stemming, sync triggers for INSERT/UPDATE/DELETE
- **XDG-compliant paths**: SQLite default at `~/.local/share/gnosis-mcp/docs.db`, no platformdirs dependency

## Testing

```bash
pytest tests/               # Unit tests (273+ tests, no DB required)
gnosis-mcp check            # Integration check against live DB
```

## Versioning

Semantic versioning (pre-1.0). Patch numbers have no upper limit (0.7.99 is valid).

- **Patch (0.7.x → 0.7.y)**: Bug fixes, small features, no new required deps
- **Minor (0.7.x → 0.8.0)**: Breaking CLI/tool API changes, or significant architectural shift
- **Major (→ 1.0.0)**: Stable tool/resource API, 300+ tests, all planned formats working

## Releases

Version lives in **4 files** — all must match:
1. `pyproject.toml` → `version = "X.Y.Z"`
2. `src/gnosis_mcp/__init__.py` → `__version__ = "X.Y.Z"`
3. `server.json` → `"version": "X.Y.Z"` (2 places)
4. `marketplace.json` → `"version": "X.Y.Z"`

Every version commit MUST:
1. Bump all 4 version files
2. Update `CHANGELOG.md`
3. Update relevant docs (`README.md`, `llms.txt`, `llms-full.txt`, `CLAUDE.md`) when adding features
4. All tests passing

**Pipeline**: push to main with changed `pyproject.toml` → `publish.yml` builds, publishes to PyPI + MCP Registry, then creates `vX.Y.Z` tag. Also triggers on manual `v*` tag pushes. No manual tagging needed.

**Remotes**: push to `selify` + `codeberg` + `github` (open-source project).

## Rules

- No pydantic, no click, no ORM
- All SQL identifiers must be validated
- Pure functions should be unit-testable without a database
- Write tools must always check `cfg.writable` first
- Backend implementations use natural SQL in their own dialect — no leaky abstraction
