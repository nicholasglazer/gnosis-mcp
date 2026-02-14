# Ansuz

MCP server for PostgreSQL documentation with pgvector search.

Ansuz (ᚨ) exposes your PostgreSQL documentation table as [Model Context Protocol](https://modelcontextprotocol.io/) tools. Works with any MCP client (Claude Code, Cursor, Windsurf, etc.).

## Features

- **3 tools**: `search_docs`, `get_doc`, `get_related`
- **2 dependencies**: `mcp` + `asyncpg`
- **Zero config**: Just set `DATABASE_URL`
- **Keyword search built-in**: Uses PostgreSQL `tsvector` (no embeddings required)
- **Custom search function**: Delegate to your own hybrid semantic+keyword function
- **Schema bootstrapping**: `ansuz init-db` creates tables + indexes

## Quickstart

```bash
pip install ansuz
export ANSUZ_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
ansuz init-db    # Create tables (idempotent)
ansuz check      # Verify connection + schema
```

Add to your MCP client config (e.g. `.claude/mcp.json`):

```json
{
  "mcpServers": {
    "docs": {
      "command": "ansuz",
      "args": ["serve"],
      "env": {
        "ANSUZ_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
      }
    }
  }
}
```

## Tools

### `search_docs(query, category?, limit?)`

Search documentation using keyword (tsvector) or hybrid semantic+keyword search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query text |
| `category` | string | null | Filter by category |
| `limit` | int | 5 | Max results (1-20) |

### `get_doc(path)`

Retrieve full document content by file path. Reassembles chunks in order.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Document file path |

### `get_related(path)`

Find related documents via bidirectional link graph.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Document file path |

## Configuration

All settings via environment variables. Only `DATABASE_URL` is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `ANSUZ_DATABASE_URL` | - | PostgreSQL connection string (falls back to `DATABASE_URL`) |
| `ANSUZ_SCHEMA` | `public` | Database schema |
| `ANSUZ_CHUNKS_TABLE` | `documentation_chunks` | Chunks table name |
| `ANSUZ_LINKS_TABLE` | `documentation_links` | Links table name |
| `ANSUZ_SEARCH_FUNCTION` | (none) | Custom search function (e.g. `internal.search_docs`) |
| `ANSUZ_COL_*` | (see below) | Column name overrides |
| `ANSUZ_POOL_MIN` | `1` | Minimum pool connections |
| `ANSUZ_POOL_MAX` | `3` | Maximum pool connections |

### Column overrides

| Variable | Default |
|----------|---------|
| `ANSUZ_COL_FILE_PATH` | `file_path` |
| `ANSUZ_COL_TITLE` | `title` |
| `ANSUZ_COL_CONTENT` | `content` |
| `ANSUZ_COL_CHUNK_INDEX` | `chunk_index` |
| `ANSUZ_COL_CATEGORY` | `category` |
| `ANSUZ_COL_AUDIENCE` | `audience` |
| `ANSUZ_COL_TAGS` | `tags` |
| `ANSUZ_COL_EMBEDDING` | `embedding` |
| `ANSUZ_COL_TSV` | `tsv` |

## Database Schema

`ansuz init-db` creates:

- **`{schema}.{chunks_table}`** -- document chunks with tsvector + optional vector column
- **`{schema}.{links_table}`** -- bidirectional document relationships
- **`{schema}.search_{chunks_table}()`** -- basic keyword search function
- GIN index on tsvector, btree indexes on file_path, category, source/target paths

## Custom Search Function

For hybrid semantic+keyword search, create your own function and point ansuz to it:

```bash
export ANSUZ_SEARCH_FUNCTION="internal.search_docs"
```

Your function must accept `(p_query_text text, p_categories text[], p_limit integer)` and return rows with columns: `file_path`, `title`, `content`, `category`, `combined_score`.

## CLI

```
ansuz serve [--transport stdio|sse]   # Start MCP server (default: stdio)
ansuz init-db [--dry-run]             # Create tables
ansuz check                           # Verify connection + schema
```

## License

MIT
