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
  <a href="llms-full.txt">Full Reference</a> &middot;
  <a href="https://miozu.com/products/gnosis-mcp">Docs</a>
</p>

<a href="https://miozu.com/products/gnosis-mcp"><img src="https://miozu.com/oss/gnosis-mcp-demo.gif" alt="Gnosis MCP demo — init, ingest, search, check" width="700"></a>

</div>

---

Gnosis MCP exposes your PostgreSQL documentation table as [Model Context Protocol](https://modelcontextprotocol.io/) tools and resources. Any MCP client can search, read, and manage your docs — Claude Code, Cursor, Windsurf, VS Code, Cline, and more.

**Two dependencies.** `mcp` + `asyncpg`. Nothing else.

## Why Gnosis MCP?

Your AI coding agent can read your code but not your documentation. RAG frameworks solve this but bring 50+ dependencies and require glue code. If you already run PostgreSQL, Gnosis MCP gives your agent searchable docs in 4 commands.

- **MCP native** — works with Claude Code, Cursor, Windsurf, Cline out of the box
- **2 dependencies** — `mcp` + `asyncpg`, nothing else
- **Your existing Postgres** — no new infrastructure, no vector DB to manage
- **Hybrid search** — keyword + semantic in one query, powered by pgvector
- **Zero config** — `init-db` creates everything, `ingest` loads your markdown

| | Gnosis MCP | LangChain RAG | Chroma + glue |
|---|---|---|---|
| Dependencies | 2 | 50+ | 15+ |
| Setup | 4 commands | 100+ lines of Python | 30+ lines |
| MCP native | Yes | No | No |
| Needs Postgres | Yes | No | No |
| Hybrid search | Built-in | Configurable | Separate |

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
- **CLI search & stats** — `gnosis-mcp search`, `gnosis-mcp stats`, `gnosis-mcp export` for quick access without MCP
- **Docker ready** — Dockerfile + docker-compose.yml included
- **Multi-table** — query across multiple doc tables with `GNOSIS_MCP_CHUNKS_TABLE=docs_v1,docs_v2`
- **Write mode** — insert, update, delete docs via MCP tools (opt-in)
- **Webhooks** — get notified on doc changes via `GNOSIS_MCP_WEBHOOK_URL`
- **Embedding support** — accept pre-computed embeddings, backfill with `gnosis-mcp embed`, built-in hybrid search
- **Embedding providers** — OpenAI, Ollama, or any OpenAI-compatible endpoint (zero new deps, uses stdlib `urllib.request`)
- **HNSW vector index** — `init-db` creates HNSW index for fast cosine similarity search
- **Schema bootstrapping** — `gnosis-mcp init-db` creates tables, indexes, keyword + hybrid search functions
- **SQL injection safe** — all identifier config values validated on startup
- **33 env vars** — fully configurable search, chunking, embedding, logging, and transport
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
| `GNOSIS_MCP_EMBED_PROVIDER` | — | Embedding provider: `openai`, `ollama`, or `custom` |
| `GNOSIS_MCP_EMBED_MODEL` | `text-embedding-3-small` | Embedding model name |
| `GNOSIS_MCP_EMBED_API_KEY` | — | API key for embedding provider |
| `GNOSIS_MCP_EMBED_URL` | — | Custom embedding endpoint URL |
| `GNOSIS_MCP_EMBED_BATCH_SIZE` | `50` | Chunks per embedding batch |
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

## Embeddings

Gnosis MCP supports 3 tiers of embedding integration, all with zero new dependencies:

**Tier 1: Accept pre-computed embeddings** — pass `embeddings` to `upsert_doc` or `query_embedding` to `search_docs` via MCP tools.

**Tier 2: Backfill with `gnosis-mcp embed`** — a sidecar command that finds chunks with NULL embeddings and fills them using OpenAI, Ollama, or any compatible API:

```bash
# Count chunks needing embeddings
gnosis-mcp embed --dry-run

# Backfill using OpenAI
export GNOSIS_MCP_EMBED_PROVIDER=openai
export GNOSIS_MCP_EMBED_API_KEY=sk-...
gnosis-mcp embed

# Or use Ollama (local, free)
gnosis-mcp embed --provider ollama --model nomic-embed-text
```

**Tier 3: Built-in hybrid search** — when `query_embedding` is provided to `search_docs`, it automatically combines keyword (tsvector) and semantic (cosine) scoring using RRF. No custom search function needed.

```bash
# CLI hybrid search (auto-embeds the query)
gnosis-mcp search "how does billing work" --embed
```

## CLI

```
gnosis-mcp serve [--transport stdio|sse] [--ingest PATH]   Start MCP server (optionally ingest first)
gnosis-mcp init-db [--dry-run]                             Create tables or preview SQL
gnosis-mcp ingest <path> [--dry-run]                       Load markdown files
gnosis-mcp search <query> [-n LIMIT] [-c CAT] [--embed]    Search (--embed for hybrid semantic+keyword)
gnosis-mcp embed [--provider P] [--model M] [--dry-run]    Backfill NULL embeddings via API
gnosis-mcp stats                                           Show document/chunk/category counts
gnosis-mcp export [-f json|markdown] [-c CAT]              Export documents as JSON or markdown
gnosis-mcp check                                           Verify connection + schema
gnosis-mcp --version                                       Show version
python -m gnosis_mcp                                       Alternative entry point
```

## Docker

```bash
docker compose up        # Starts gnosis-mcp + pgvector database
```

Or build standalone:

```bash
docker build -t gnosis-mcp .
docker run -e GNOSIS_MCP_DATABASE_URL=postgresql://... gnosis-mcp serve
```

## Development

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 138 tests, no database required
ruff check src/ tests/    # lint
```

## Architecture

```
src/gnosis_mcp/
├── config.py    GnosisMcpConfig — frozen dataclass, 33 env vars, SQL injection validation
├── db.py        asyncpg pool + FastMCP lifespan context manager
├── server.py    FastMCP server — 6 tools, 3 resources, webhook helper
├── ingest.py    File scanner — markdown chunking, frontmatter, content hashing
├── schema.py    SQL template for init-db (chunks + links + keyword/hybrid search + HNSW index)
├── embed.py     Embedding sidecar — provider abstraction (openai/ollama/custom), batch backfill
└── cli.py       argparse CLI — serve, init-db, ingest, search, embed, stats, export, check
```

## AI-Friendly Docs

| File | Description |
|------|-------------|
| [`llms.txt`](llms.txt) | Quick overview for AI agents |
| [`llms-full.txt`](llms-full.txt) | Complete reference in one file |
| [`llms-install.md`](llms-install.md) | Step-by-step install guide |

## Contributing

Contributions are welcome. The codebase is intentionally small — 7 modules, 2 dependencies, no ORM. If you're thinking about a change, here's how to get started:

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

All tests run without a database. Keep it that way. If your feature needs DB calls, mock them or add a separate integration test.

**Good first contributions:**
- New embedding providers (Cohere, Voyage, local models)
- Additional export formats (CSV, JSONL)
- Ingestion support for RST, AsciiDoc, or HTML
- Search result highlighting
- Bug reports with reproduction steps

**Design constraints to respect:**
- No new runtime dependencies (stdlib is fine)
- Write tools must check `cfg.writable`
- All SQL identifiers must be validated
- Pure functions should be unit-testable without a database

Open an issue first for larger changes so we can discuss the approach.

## Sponsors

If Gnosis MCP saves you time, consider [sponsoring the project](https://github.com/sponsors/nicholasglazer).

## License

[MIT](LICENSE)
