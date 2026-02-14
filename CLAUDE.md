# Stele -- MCP Documentation Server

Open-source Python MCP server for PostgreSQL documentation with pgvector search. Part of the miozu ecosystem.

## Architecture

```
src/stele/
├── config.py   # SteleConfig frozen dataclass, STELE_* env vars, identifier validation
├── db.py       # asyncpg pool + FastMCP lifespan context manager
├── server.py   # FastMCP server: 6 tools + 3 resources + webhook helper
├── schema.py   # SQL template for init-db (chunks + links tables)
└── cli.py      # argparse CLI: serve, init-db, check
```

## Dependencies

Only 2: `mcp>=1.20`, `asyncpg>=0.29`. No click, no pydantic, no ORM.

## Tools

### Read (always available)
1. **search_docs(query, category?, limit?)** -- keyword (tsvector) or hybrid search via custom function
2. **get_doc(path, max_length?)** -- reassemble document chunks by file_path + chunk_index (optional truncation)
3. **get_related(path)** -- bidirectional link graph query

### Write (requires STELE_WRITABLE=true)
4. **upsert_doc(path, content, title?, category?, audience?, tags?)** -- insert/replace document with auto-chunking
5. **delete_doc(path)** -- delete document chunks + links
6. **update_metadata(path, title?, category?, audience?, tags?)** -- update metadata on all chunks

## Resources

- **stele://docs** -- list all documents (path, title, category, chunk count)
- **stele://docs/{path}** -- read document content by path
- **stele://categories** -- list categories with doc counts

## Key Design Decisions

- **FastMCP lifespan pattern**: Pool created once via `app_lifespan()`, shared across tool calls
- **SQL injection prevention**: All identifiers validated via regex in `SteleConfig.__post_init__()`
- **Multi-table support**: `STELE_CHUNKS_TABLE` accepts comma-separated tables, queries use `UNION ALL`
- **Write gating**: Write tools check `cfg.writable` and return error if disabled
- **Webhook notifications**: Fire-and-forget POST to `STELE_WEBHOOK_URL` on write operations
- **Custom search delegation**: Set `STELE_SEARCH_FUNCTION` to use your own hybrid search
- **Column overrides**: `STELE_COL_*` are for connecting to existing tables with non-standard names
- **No embedding generation**: Users bring their own embeddings

## Testing

```bash
pytest tests/               # Unit tests (54 tests, no DB required)
stele check                 # Integration check against live DB
```

## Rules

- Keep dependencies minimal (2 only)
- No pydantic, no click, no ORM
- All SQL identifiers must be validated
- Pure functions should be unit-testable without a database
- Write tools must always check `cfg.writable` first
