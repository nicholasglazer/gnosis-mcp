# Ansuz

MCP server for PostgreSQL documentation with pgvector search.

Ansuz (ᚨ) exposes your PostgreSQL documentation table as [Model Context Protocol](https://modelcontextprotocol.io/) tools. Works with any MCP client (Claude Code, Cursor, Windsurf, etc.).

## Features

- **3 tools**: `search_docs`, `get_doc`, `get_related`
- **2 dependencies**: `mcp` + `asyncpg`
- **Zero config**: Just set `DATABASE_URL`
- **Keyword search built-in**: Uses PostgreSQL `tsvector` (no embeddings required)
- **Custom search function**: Delegate to your own hybrid semantic+keyword function
- **Schema bootstrapping**: `ansuz init-db` creates tables, indexes, and a search function
- **SQL injection safe**: All identifier config values validated on startup

## Quickstart

```bash
pip install ansuz
export ANSUZ_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
ansuz init-db    # Create tables (idempotent)
ansuz check      # Verify connection + schema
```

Add to your MCP client config and start using the tools.

### Claude Code

Add to `.claude/mcp.json`:

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

### Cursor

Add to `.cursor/mcp.json`:

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

### Custom search function (hybrid semantic+keyword)

If you have a PostgreSQL function that does hybrid search (e.g. combining embeddings with tsvector):

```json
{
  "mcpServers": {
    "docs": {
      "command": "ansuz",
      "args": ["serve"],
      "env": {
        "ANSUZ_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb",
        "ANSUZ_SCHEMA": "internal",
        "ANSUZ_SEARCH_FUNCTION": "internal.search_docs"
      }
    }
  }
}
```

Your function must accept `(p_query_text text, p_categories text[], p_limit integer)` and return rows with columns: `file_path`, `title`, `content`, `category`, `combined_score`.

## Tools

### `search_docs(query, category?, limit?)`

Search documentation using keyword (tsvector) or hybrid semantic+keyword search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query text |
| `category` | string | null | Filter by category |
| `limit` | int | 5 | Max results (1-20) |

Example response:

```json
[
  {
    "file_path": "curated/guides/billing-guide.md",
    "title": "Billing & Credits System",
    "content_preview": "The platform uses a credit-based billing system. Each workspace has...",
    "score": 0.0288
  },
  {
    "file_path": "curated/guides/stripe-integration.md",
    "title": "Stripe Integration Guide",
    "content_preview": "Stripe handles payment processing for subscriptions and one-time...",
    "score": 0.0245
  }
]
```

### `get_doc(path)`

Retrieve full document content by file path. Reassembles chunks in order.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Document file path |

Example response:

```json
{
  "title": "Design System Guide",
  "content": "# Design System\n\nThis guide covers the visual design...",
  "category": "guides",
  "audience": "all",
  "tags": ["design", "ui", "components"]
}
```

### `get_related(path)`

Find related documents via bidirectional link graph.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Document file path |

Example response:

```json
[
  {
    "related_path": "curated/guides/component-library.md",
    "relation_type": "references",
    "direction": "outgoing"
  },
  {
    "related_path": "curated/architecture/frontend-architecture.md",
    "relation_type": "references",
    "direction": "incoming"
  }
]
```

## Configuration

All settings via environment variables. Only `DATABASE_URL` is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `ANSUZ_DATABASE_URL` | - | PostgreSQL connection string (falls back to `DATABASE_URL`) |
| `ANSUZ_SCHEMA` | `public` | Database schema |
| `ANSUZ_CHUNKS_TABLE` | `documentation_chunks` | Chunks table name |
| `ANSUZ_LINKS_TABLE` | `documentation_links` | Links table name |
| `ANSUZ_SEARCH_FUNCTION` | (none) | Custom search function (e.g. `internal.search_docs`) |
| `ANSUZ_EMBEDDING_DIM` | `1536` | Embedding vector dimension (for `init-db`) |
| `ANSUZ_POOL_MIN` | `1` | Minimum pool connections |
| `ANSUZ_POOL_MAX` | `3` | Maximum pool connections |

### Column name overrides

Use these when connecting to an existing table with non-standard column names. These do **not** affect `ansuz init-db` (which always creates standard columns).

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

Preview the SQL without executing:

```bash
ansuz init-db --dry-run
```

## Populating the Database

Ansuz is a read-only server. Insert your documents however you prefer:

```sql
INSERT INTO public.documentation_chunks (file_path, chunk_index, title, content, category)
VALUES
  ('guides/quickstart.md', 0, 'Getting Started', 'Welcome to the platform...', 'guides'),
  ('guides/quickstart.md', 1, 'Getting Started', 'Next, configure your API key...', 'guides');

INSERT INTO public.documentation_links (source_path, target_path, relation_type)
VALUES
  ('guides/quickstart.md', 'guides/api-reference.md', 'references');
```

For embeddings, generate them with your preferred model and update the `embedding` column:

```sql
UPDATE public.documentation_chunks
SET embedding = $1::vector
WHERE file_path = $2 AND chunk_index = $3;
```

## CLI

```
ansuz serve [--transport stdio|sse]   # Start MCP server (default: stdio)
ansuz init-db [--dry-run]             # Create tables (or preview SQL)
ansuz check                           # Verify connection + schema
ansuz --version                       # Show version
```

## Development

```bash
git clone https://github.com/miozu-com/ansuz.git
cd ansuz
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # Run tests
ruff check src/ tests/    # Lint
```

## License

MIT
