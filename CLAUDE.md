# Ansuz -- MCP Documentation Server

Open-source Python MCP server for PostgreSQL documentation with pgvector search. Part of the miozu ecosystem.

## Architecture

```
src/ansuz/
├── config.py   # AnsuzConfig frozen dataclass, ANSUZ_* env vars, identifier validation
├── db.py       # asyncpg pool + FastMCP lifespan context manager
├── server.py   # FastMCP server + 3 tools (search_docs, get_doc, get_related)
├── schema.py   # SQL template for init-db (chunks + links tables)
└── cli.py      # argparse CLI: serve, init-db, check
```

## Dependencies

Only 2: `mcp>=1.20`, `asyncpg>=0.29`. No click, no pydantic, no ORM.

## Tools

1. **search_docs(query, category?, limit?)** -- keyword (tsvector) or hybrid search via custom function
2. **get_doc(path)** -- reassemble document chunks by file_path + chunk_index
3. **get_related(path)** -- bidirectional link graph query

## Key Design Decisions

- **FastMCP lifespan pattern**: Pool created once via `app_lifespan()`, shared across tool calls
- **SQL injection prevention**: All identifiers validated via regex in `AnsuzConfig.__post_init__()`
- **Custom search delegation**: Set `ANSUZ_SEARCH_FUNCTION` to use your own hybrid search. The function must return `file_path, title, content, category, combined_score` (fixed contract, not affected by `ANSUZ_COL_*`)
- **Column overrides**: `ANSUZ_COL_*` are for connecting to existing tables with non-standard names. They do NOT affect `ansuz init-db`
- **No embedding generation**: Read-only server. Users bring their own embeddings
- **Configurable embedding dimension**: `ANSUZ_EMBEDDING_DIM` (default 1536) for init-db

## Testing

```bash
pytest tests/               # Unit tests (no DB required)
ansuz check                 # Integration check against live DB
```

## Rules

- Keep dependencies minimal (2 only)
- No pydantic, no click, no ORM
- All SQL identifiers must be validated
- Pure functions should be unit-testable without a database
