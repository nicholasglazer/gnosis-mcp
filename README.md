<!-- gnosis-mcp -->

# Gnosis MCP

[![PyPI](https://img.shields.io/pypi/v/gnosis-mcp)](https://pypi.org/project/gnosis-mcp/)
[![Downloads](https://img.shields.io/pypi/dm/gnosis-mcp)](https://pypi.org/project/gnosis-mcp/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io/)

MCP server for PostgreSQL documentation with pgvector search.

Gnosis MCP exposes your PostgreSQL documentation table as [Model Context Protocol](https://modelcontextprotocol.io/) tools and resources. Works with any MCP client (Claude Code, Cursor, Windsurf, Cline, etc.).

> **PyPI:** `gnosis-mcp` | **CLI:** `gnosis-mcp` | **Import:** `gnosis_mcp`

## Features

- **6 tools**: `search_docs`, `get_doc`, `get_related`, `upsert_doc`, `delete_doc`, `update_metadata`
- **3 resources**: `gnosis://docs`, `gnosis://docs/{path}`, `gnosis://categories`
- **2 dependencies**: `mcp` + `asyncpg`
- **Zero config**: Just set `DATABASE_URL`
- **Multi-table**: Query across multiple doc tables with `GNOSIS_MCP_CHUNKS_TABLE=docs_v1,docs_v2`
- **Write mode**: Insert/update/delete docs via MCP tools (opt-in via `GNOSIS_MCP_WRITABLE=true`)
- **Webhooks**: Get notified when docs change via `GNOSIS_MCP_WEBHOOK_URL`
- **Keyword search built-in**: Uses PostgreSQL `tsvector` (no embeddings required)
- **Custom search function**: Delegate to your own hybrid semantic+keyword function
- **Schema bootstrapping**: `gnosis-mcp init-db` creates tables, indexes, and a search function
- **SQL injection safe**: All identifier config values validated on startup
- **Fully configurable**: 25+ env vars for tuning search, chunking, logging, and transport

## Quickstart

```bash
pip install gnosis-mcp
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
gnosis-mcp init-db    # Create tables (idempotent)
gnosis-mcp check      # Verify connection + schema
```

Add to your MCP client config and start using the tools.

### Claude Code

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
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
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
      }
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
      }
    }
  }
}
```

### Cline

Add to Cline MCP settings:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
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
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb",
        "GNOSIS_MCP_SCHEMA": "internal",
        "GNOSIS_MCP_SEARCH_FUNCTION": "internal.search_docs"
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
    "GNOSIS_MCP_CHUNKS_TABLE": "documentation_chunks,api_docs,tutorial_chunks"
  }
}
```

All tables must share the same column structure. Searches and reads use `UNION ALL` across all tables.

### Write mode

Enable AI agents to insert/update/delete documentation:

```json
{
  "env": {
    "GNOSIS_MCP_WRITABLE": "true",
    "GNOSIS_MCP_WEBHOOK_URL": "https://your-server.com/docs-changed"
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
| `limit` | int | 5 | Max results (1-N, default 5) |

### `get_doc(path, max_length?)`

Retrieve full document content by file path. Reassembles chunks in order.

### `get_related(path)`

Find related documents via bidirectional link graph.

### `upsert_doc(path, content, title?, category?, audience?, tags?)`

Insert or replace a document. Auto-splits into chunks at paragraph boundaries. Requires `GNOSIS_MCP_WRITABLE=true`.

### `delete_doc(path)`

Delete a document and all its chunks + links. Requires `GNOSIS_MCP_WRITABLE=true`.

### `update_metadata(path, title?, category?, audience?, tags?)`

Update metadata fields on a document. Only provided fields are changed. Requires `GNOSIS_MCP_WRITABLE=true`.

## Resources

### `gnosis://docs`

List all documents with title, category, and chunk count.

### `gnosis://docs/{path}`

Read a document by path as an MCP resource.

### `gnosis://categories`

List all categories with document counts.

## Configuration

All settings via environment variables. Only `DATABASE_URL` is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | - | PostgreSQL connection string (falls back to `DATABASE_URL`) |
| `GNOSIS_MCP_SCHEMA` | `public` | Database schema |
| `GNOSIS_MCP_CHUNKS_TABLE` | `documentation_chunks` | Chunks table name (comma-separated for multi-table) |
| `GNOSIS_MCP_LINKS_TABLE` | `documentation_links` | Links table name |
| `GNOSIS_MCP_SEARCH_FUNCTION` | (none) | Custom search function (e.g. `internal.search_docs`) |
| `GNOSIS_MCP_EMBEDDING_DIM` | `1536` | Embedding vector dimension (for `init-db`) |
| `GNOSIS_MCP_POOL_MIN` | `1` | Minimum pool connections |
| `GNOSIS_MCP_POOL_MAX` | `3` | Maximum pool connections |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable write tools (`true`, `1`, or `yes`) |
| `GNOSIS_MCP_WEBHOOK_URL` | (none) | URL to POST when docs change |
| `GNOSIS_MCP_CONTENT_PREVIEW_CHARS` | `200` | Characters shown in search result previews (min 50) |
| `GNOSIS_MCP_CHUNK_SIZE` | `4000` | Max characters per chunk when splitting documents (min 500) |
| `GNOSIS_MCP_SEARCH_LIMIT_MAX` | `20` | Maximum allowed search result limit (min 1) |
| `GNOSIS_MCP_WEBHOOK_TIMEOUT` | `5` | Webhook HTTP timeout in seconds (min 1) |
| `GNOSIS_MCP_TRANSPORT` | `stdio` | Server transport protocol (`stdio` or `sse`) |
| `GNOSIS_MCP_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |

### Column name overrides

Use these when connecting to an existing table with non-standard column names. These do **not** affect `gnosis-mcp init-db` (which always creates standard columns).

| Variable | Default |
|----------|---------|
| `GNOSIS_MCP_COL_FILE_PATH` | `file_path` |
| `GNOSIS_MCP_COL_TITLE` | `title` |
| `GNOSIS_MCP_COL_CONTENT` | `content` |
| `GNOSIS_MCP_COL_CHUNK_INDEX` | `chunk_index` |
| `GNOSIS_MCP_COL_CATEGORY` | `category` |
| `GNOSIS_MCP_COL_AUDIENCE` | `audience` |
| `GNOSIS_MCP_COL_TAGS` | `tags` |
| `GNOSIS_MCP_COL_EMBEDDING` | `embedding` |
| `GNOSIS_MCP_COL_TSV` | `tsv` |

## Database Schema

`gnosis-mcp init-db` creates:

- **`{schema}.{chunks_table}`** -- document chunks with tsvector + optional vector column
- **`{schema}.{links_table}`** -- bidirectional document relationships
- **`{schema}.search_{chunks_table}()`** -- basic keyword search function
- GIN index on tsvector, btree indexes on file_path, category, source/target paths

Preview the SQL without executing:

```bash
gnosis-mcp init-db --dry-run
```

## CLI

```
gnosis-mcp serve [--transport stdio|sse]   # Start MCP server (default: stdio)
gnosis-mcp init-db [--dry-run]             # Create tables (or preview SQL)
gnosis-mcp check                           # Verify connection + schema
gnosis-mcp --version                       # Show version
```

## Development

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # Run tests (69 tests, no DB required)
ruff check src/ tests/    # Lint
```

## License

MIT
