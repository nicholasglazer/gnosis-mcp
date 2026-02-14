# Stele

MCP server for PostgreSQL documentation with pgvector search.

Stele exposes your PostgreSQL documentation table as [Model Context Protocol](https://modelcontextprotocol.io/) tools and resources. Works with any MCP client (Claude Code, Cursor, Windsurf, etc.).

## Features

- **6 tools**: `search_docs`, `get_doc`, `get_related`, `upsert_doc`, `delete_doc`, `update_metadata`
- **3 resources**: `stele://docs`, `stele://docs/{path}`, `stele://categories`
- **2 dependencies**: `mcp` + `asyncpg`
- **Zero config**: Just set `DATABASE_URL`
- **Multi-table**: Query across multiple doc tables with `STELE_CHUNKS_TABLE=docs_v1,docs_v2`
- **Write mode**: Insert/update/delete docs via MCP tools (opt-in via `STELE_WRITABLE=true`)
- **Webhooks**: Get notified when docs change via `STELE_WEBHOOK_URL`
- **Keyword search built-in**: Uses PostgreSQL `tsvector` (no embeddings required)
- **Custom search function**: Delegate to your own hybrid semantic+keyword function
- **Schema bootstrapping**: `stele init-db` creates tables, indexes, and a search function
- **SQL injection safe**: All identifier config values validated on startup

## Quickstart

```bash
pip install stele
export STELE_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
stele init-db    # Create tables (idempotent)
stele check      # Verify connection + schema
```

Add to your MCP client config and start using the tools.

### Claude Code

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "stele",
      "args": ["serve"],
      "env": {
        "STELE_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "stele",
      "args": ["serve"],
      "env": {
        "STELE_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
      }
    }
  }
}
```

### Custom search function (hybrid semantic+keyword)

If you have a PostgreSQL function that does hybrid search (e.g. combining embeddings with tsvector):

```json
{
  "mcpServers": {
    "docs": {
      "command": "stele",
      "args": ["serve"],
      "env": {
        "STELE_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb",
        "STELE_SCHEMA": "internal",
        "STELE_SEARCH_FUNCTION": "internal.search_docs"
      }
    }
  }
}
```

Your function must accept `(p_query_text text, p_categories text[], p_limit integer)` and return rows with columns: `file_path`, `title`, `content`, `category`, `combined_score`.

### Multi-table mode

Serve documentation from multiple tables simultaneously:

```json
{
  "env": {
    "STELE_CHUNKS_TABLE": "documentation_chunks,api_docs,tutorial_chunks"
  }
}
```

All tables must share the same column structure. Searches and reads use `UNION ALL` across all tables.

### Write mode

Enable AI agents to insert/update/delete documentation:

```json
{
  "env": {
    "STELE_WRITABLE": "true",
    "STELE_WEBHOOK_URL": "https://your-server.com/docs-changed"
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

### `get_related(path)`

Find related documents via bidirectional link graph.

### `upsert_doc(path, content, title?, category?, audience?, tags?)`

Insert or replace a document. Auto-splits into chunks at paragraph boundaries. Requires `STELE_WRITABLE=true`.

### `delete_doc(path)`

Delete a document and all its chunks + links. Requires `STELE_WRITABLE=true`.

### `update_metadata(path, title?, category?, audience?, tags?)`

Update metadata fields on a document. Only provided fields are changed. Requires `STELE_WRITABLE=true`.

## Resources

### `stele://docs`

List all documents with title, category, and chunk count.

### `stele://docs/{path}`

Read a document by path as an MCP resource.

### `stele://categories`

List all categories with document counts.

## Configuration

All settings via environment variables. Only `DATABASE_URL` is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `STELE_DATABASE_URL` | - | PostgreSQL connection string (falls back to `DATABASE_URL`) |
| `STELE_SCHEMA` | `public` | Database schema |
| `STELE_CHUNKS_TABLE` | `documentation_chunks` | Chunks table name (comma-separated for multi-table) |
| `STELE_LINKS_TABLE` | `documentation_links` | Links table name |
| `STELE_SEARCH_FUNCTION` | (none) | Custom search function (e.g. `internal.search_docs`) |
| `STELE_EMBEDDING_DIM` | `1536` | Embedding vector dimension (for `init-db`) |
| `STELE_POOL_MIN` | `1` | Minimum pool connections |
| `STELE_POOL_MAX` | `3` | Maximum pool connections |
| `STELE_WRITABLE` | `false` | Enable write tools (`true`, `1`, or `yes`) |
| `STELE_WEBHOOK_URL` | (none) | URL to POST when docs change |

### Column name overrides

Use these when connecting to an existing table with non-standard column names. These do **not** affect `stele init-db` (which always creates standard columns).

| Variable | Default |
|----------|---------|
| `STELE_COL_FILE_PATH` | `file_path` |
| `STELE_COL_TITLE` | `title` |
| `STELE_COL_CONTENT` | `content` |
| `STELE_COL_CHUNK_INDEX` | `chunk_index` |
| `STELE_COL_CATEGORY` | `category` |
| `STELE_COL_AUDIENCE` | `audience` |
| `STELE_COL_TAGS` | `tags` |
| `STELE_COL_EMBEDDING` | `embedding` |
| `STELE_COL_TSV` | `tsv` |

## Database Schema

`stele init-db` creates:

- **`{schema}.{chunks_table}`** -- document chunks with tsvector + optional vector column
- **`{schema}.{links_table}`** -- bidirectional document relationships
- **`{schema}.search_{chunks_table}()`** -- basic keyword search function
- GIN index on tsvector, btree indexes on file_path, category, source/target paths

Preview the SQL without executing:

```bash
stele init-db --dry-run
```

## CLI

```
stele serve [--transport stdio|sse]   # Start MCP server (default: stdio)
stele init-db [--dry-run]             # Create tables (or preview SQL)
stele check                           # Verify connection + schema
stele --version                       # Show version
```

## Development

```bash
git clone https://github.com/miozu-com/stele.git
cd stele
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # Run tests
ruff check src/ tests/    # Lint
```

## License

MIT
