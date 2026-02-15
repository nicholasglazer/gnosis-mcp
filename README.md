<div align="center">

<h1>Gnosis MCP</h1>

<p><strong>Serve your PostgreSQL docs to AI agents over MCP.</strong></p>

<p>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/v/gnosis-mcp?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/pyversions/gnosis-mcp" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/actions"><img src="https://github.com/nicholasglazer/gnosis-mcp/actions/workflows/publish.yml/badge.svg" alt="CI"></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#tools">Tools</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="llms-full.txt">Full Reference</a>
</p>

</div>

---

Gnosis MCP exposes your PostgreSQL documentation table as [Model Context Protocol](https://modelcontextprotocol.io/) tools and resources. Any MCP client can search, read, and manage your docs — Claude Code, Cursor, Windsurf, VS Code, Cline, and more.

**Two dependencies.** `mcp` + `asyncpg`. Nothing else.

## Quick Start

```bash
pip install gnosis-mcp
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
gnosis-mcp init-db              # create tables
gnosis-mcp ingest ./docs/       # load markdown files
gnosis-mcp search "auth flow"   # verify it works
gnosis-mcp serve                 # start MCP server
```

Or run without installing:

```bash
uvx gnosis-mcp serve
```

### Add to your MCP client

<details open>
<summary><strong>Claude Code</strong></summary>

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

</details>

<details>
<summary><strong>Cursor</strong></summary>

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

</details>

<details>
<summary><strong>Windsurf</strong></summary>

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

</details>

<details>
<summary><strong>Cline</strong></summary>

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

</details>

## Tools

| Tool | Description | Mode |
|------|-------------|------|
| `search_docs` | Keyword or hybrid semantic+keyword search | Read |
| `get_doc` | Retrieve full document by path | Read |
| `get_related` | Find related docs via link graph | Read |
| `upsert_doc` | Create or replace a document | Write |
| `delete_doc` | Remove a document and its links | Write |
| `update_metadata` | Update title, category, audience, tags | Write |

> [!NOTE]
> Write tools require `GNOSIS_MCP_WRITABLE=true`. Read tools are always available.

### Resources

| URI | Description |
|-----|-------------|
| `gnosis://docs` | List all documents with title, category, chunk count |
| `gnosis://docs/{path}` | Read document content by path |
| `gnosis://categories` | List categories with document counts |

## Features

- **File ingestion** — `gnosis-mcp ingest ./docs/` scans markdown, chunks by H2 headings, loads into PostgreSQL
- **Hybrid search** — built-in tsvector keyword search, or bring your own semantic+keyword function
- **Multi-table** — query across multiple doc tables with `GNOSIS_MCP_CHUNKS_TABLE=docs_v1,docs_v2`
- **Write mode** — insert, update, delete docs via MCP tools (opt-in)
- **Webhooks** — get notified on doc changes via `GNOSIS_MCP_WEBHOOK_URL`
- **Schema bootstrapping** — `gnosis-mcp init-db` creates tables, indexes, and search function
- **SQL injection safe** — all identifier config values validated on startup
- **28 env vars** — fully configurable search, chunking, logging, and transport
- **Typed** — PEP 561 `py.typed` marker included

## Configuration

All settings via environment variables. Only `DATABASE_URL` is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | *required* | PostgreSQL connection string (falls back to `DATABASE_URL`) |
| `GNOSIS_MCP_SCHEMA` | `public` | Database schema |
| `GNOSIS_MCP_CHUNKS_TABLE` | `documentation_chunks` | Chunks table (comma-separated for multi-table) |
| `GNOSIS_MCP_LINKS_TABLE` | `documentation_links` | Links table |
| `GNOSIS_MCP_SEARCH_FUNCTION` | — | Custom search function (e.g. `internal.search_docs`) |
| `GNOSIS_MCP_EMBEDDING_DIM` | `1536` | Embedding vector dimension (for `init-db`) |
| `GNOSIS_MCP_POOL_MIN` | `1` | Minimum pool connections |
| `GNOSIS_MCP_POOL_MAX` | `3` | Maximum pool connections |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable write tools (`true`, `1`, or `yes`) |
| `GNOSIS_MCP_WEBHOOK_URL` | — | URL to POST when docs change |
| `GNOSIS_MCP_CONTENT_PREVIEW_CHARS` | `200` | Characters in search result previews (min 50) |
| `GNOSIS_MCP_CHUNK_SIZE` | `4000` | Max characters per chunk (min 500) |
| `GNOSIS_MCP_SEARCH_LIMIT_MAX` | `20` | Maximum allowed search limit (min 1) |
| `GNOSIS_MCP_WEBHOOK_TIMEOUT` | `5` | Webhook HTTP timeout in seconds (min 1) |
| `GNOSIS_MCP_TRANSPORT` | `stdio` | Server transport (`stdio` or `sse`) |
| `GNOSIS_MCP_LOG_LEVEL` | `INFO` | Log level (`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`) |

<details>
<summary><strong>Column name overrides</strong></summary>

Use these when connecting to an existing table with non-standard column names. These do **not** affect `gnosis-mcp init-db`.

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
| `GNOSIS_MCP_COL_SOURCE_PATH` | `source_path` |
| `GNOSIS_MCP_COL_TARGET_PATH` | `target_path` |
| `GNOSIS_MCP_COL_RELATION_TYPE` | `relation_type` |

</details>

<details>
<summary><strong>Custom search function</strong></summary>

Set `GNOSIS_MCP_SEARCH_FUNCTION` to delegate search to your own PostgreSQL function (e.g. hybrid semantic+keyword):

```sql
CREATE FUNCTION my_schema.my_search(
    p_query_text text,
    p_categories text[],
    p_limit integer
) RETURNS TABLE (
    file_path text,
    title text,
    content text,
    category text,
    combined_score double precision
) ...
```

```bash
GNOSIS_MCP_SEARCH_FUNCTION=my_schema.my_search
```

</details>

<details>
<summary><strong>Multi-table mode</strong></summary>

Serve documentation from multiple tables simultaneously:

```bash
GNOSIS_MCP_CHUNKS_TABLE=documentation_chunks,api_docs,tutorial_chunks
```

All tables must share the same column structure. Reads use `UNION ALL` across all tables. Writes target the first table.

> [!IMPORTANT]
> `gnosis-mcp init-db` only creates the first table. Create additional tables manually with the same schema.

</details>

## CLI

```
gnosis-mcp serve [--transport stdio|sse]          Start MCP server
gnosis-mcp init-db [--dry-run]                    Create tables or preview SQL
gnosis-mcp ingest <path> [--dry-run]              Load markdown files
gnosis-mcp search <query> [-n LIMIT] [-c CAT]     Search from the command line
gnosis-mcp check                                  Verify connection + schema
gnosis-mcp --version                              Show version
python -m gnosis_mcp                              Alternative entry point
```

## Development

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 92 tests, no database required
ruff check src/ tests/    # lint
```

## Architecture

```
src/gnosis_mcp/
├── config.py    GnosisMcpConfig — frozen dataclass, 28 env vars, SQL injection validation
├── db.py        asyncpg pool + FastMCP lifespan context manager
├── server.py    FastMCP server — 6 tools, 3 resources, webhook helper
├── ingest.py    File scanner — markdown chunking, frontmatter, content hashing
├── schema.py    SQL template for init-db (chunks + links + search function)
└── cli.py       argparse CLI — serve, init-db, ingest, search, check
```

## AI-Friendly Docs

| File | Description |
|------|-------------|
| [`llms.txt`](llms.txt) | Quick overview for AI agents |
| [`llms-full.txt`](llms-full.txt) | Complete reference in one file |
| [`llms-install.md`](llms-install.md) | Step-by-step install guide |

## License

[MIT](LICENSE)
