# Ansuz -- MCP Documentation Server

Open-source Python MCP server for PostgreSQL documentation with pgvector search. Part of the miozu ecosystem.

## Architecture

```
src/ansuz/
├── config.py   # AnsuzConfig frozen dataclass, reads ANSUZ_* env vars
├── db.py       # asyncpg pool + FastMCP lifespan context manager
├── server.py   # FastMCP server + 3 tools (search_docs, get_doc, get_related)
├── schema.py   # SQL template for init-db (chunks + links tables)
└── cli.py      # argparse CLI: serve, init-db, check
```

## Dependencies

Only 2: `mcp>=1.20`, `asyncpg>=0.29`. No click, no pydantic, no ORM.

## Tools

1. **search_docs** -- keyword (tsvector) or hybrid search via custom function
2. **get_doc** -- reassemble document chunks by file_path + chunk_index
3. **get_related** -- bidirectional link graph query

## Key Design Decisions

- **FastMCP lifespan pattern**: Pool created once via `app_lifespan()`, shared across tool calls
- **Custom search delegation**: Set `ANSUZ_SEARCH_FUNCTION` to use your own hybrid search
- **All column names configurable**: `ANSUZ_COL_*` env vars for any schema
- **No embedding generation**: Read-only server. Users bring their own embeddings.

## Testing

```bash
pytest tests/               # Unit tests (no DB required)
ansuz check                 # Integration check against live DB
```

## Git Remotes

| Remote | URL |
|--------|-----|
| selify | `git@git.selify.ai:selify/ansuz.git` |
| codeberg | `ssh://git@codeberg.org/miozu/ansuz.git` |
| github | `git@github.com:miozu-com/ansuz.git` |
