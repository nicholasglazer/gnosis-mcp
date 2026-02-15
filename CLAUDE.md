# Gnosis MCP -- MCP Documentation Server

Open-source Python MCP server for PostgreSQL documentation with pgvector search.

## Architecture

```
src/gnosis_mcp/
├── config.py   # GnosisMcpConfig frozen dataclass, GNOSIS_MCP_* env vars, identifier validation
├── db.py       # asyncpg pool + FastMCP lifespan context manager
├── server.py   # FastMCP server: 6 tools + 3 resources + webhook helper
├── ingest.py   # File ingestion: scan markdown, chunk by H2, frontmatter, content hashing
├── schema.py   # SQL template for init-db (chunks + links + HNSW index + hybrid search)
├── embed.py    # Embedding sidecar: provider abstraction (openai/ollama/custom), batch backfill
└── cli.py      # argparse CLI: serve, init-db, ingest, search, embed, stats, export, check
```

## Dependencies

Only 2: `mcp>=1.20`, `asyncpg>=0.29`. No click, no pydantic, no ORM.

## Tools

### Read (always available)
1. **search_docs(query, category?, limit?, query_embedding?)** -- keyword (tsvector), hybrid (with embedding), or custom function search
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

- **FastMCP lifespan pattern**: Pool created once via `app_lifespan()`, shared across tool calls
- **SQL injection prevention**: All identifiers validated via regex in `GnosisMcpConfig.__post_init__()`
- **Multi-table support**: `GNOSIS_MCP_CHUNKS_TABLE` accepts comma-separated tables, queries use `UNION ALL`
- **Write gating**: Write tools check `cfg.writable` and return error if disabled
- **Webhook notifications**: Fire-and-forget POST to `GNOSIS_MCP_WEBHOOK_URL` on write operations
- **Custom search delegation**: Set `GNOSIS_MCP_SEARCH_FUNCTION` to use your own hybrid search
- **Column overrides**: `GNOSIS_MCP_COL_*` are for connecting to existing tables with non-standard names
- **H2-based chunking**: `ingest` splits markdown by H2 headers (smarter than paragraph boundaries)
- **Content hashing**: `ingest` skips unchanged files using SHA-256 hash comparison
- **3-tier embedding support**: Accept pre-computed embeddings via tools, backfill with `gnosis-mcp embed`, built-in hybrid search when `query_embedding` is provided
- **Zero embedding deps**: Embedding providers use stdlib `urllib.request` — no new runtime dependencies
- **HNSW vector index**: `init-db` creates an HNSW index for fast cosine similarity search

## Testing

```bash
pytest tests/               # Unit tests (138 tests, no DB required)
gnosis-mcp check            # Integration check against live DB
```

## Rules

- Keep dependencies minimal (2 only)
- No pydantic, no click, no ORM
- All SQL identifiers must be validated
- Pure functions should be unit-testable without a database
- Write tools must always check `cfg.writable` first
