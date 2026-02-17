<div align="center">

<h1>Gnosis MCP</h1>

<p><strong>Give your AI agent a searchable knowledge base. Backed by PostgreSQL.</strong></p>

<p>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/v/gnosis-mcp?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/pyversions/gnosis-mcp" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/actions"><img src="https://github.com/nicholasglazer/gnosis-mcp/actions/workflows/publish.yml/badge.svg" alt="CI"></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#claude-code-plugin">Claude Code Plugin</a> &middot;
  <a href="#what-it-does">What It Does</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="llms-full.txt">Full Reference</a> &middot;
  <a href="https://miozu.com/products/gnosis-mcp">Docs</a>
</p>

<a href="https://miozu.com/products/gnosis-mcp"><img src="https://miozu.com/oss/gnosis-mcp-demo.gif" alt="Gnosis MCP demo — init, ingest, search, check" width="700"></a>

</div>

---

AI coding agents can read your source code but not your documentation. They guess at architecture, miss established patterns, and hallucinate details they could have looked up.

Gnosis MCP fixes this. It loads your markdown docs into PostgreSQL and exposes them as [MCP](https://modelcontextprotocol.io/) tools — search, read, and manage — that any compatible agent can call. Claude Code, Cursor, Windsurf, Cline, VS Code.

Two runtime dependencies. Four commands to set up. Uses the PostgreSQL you already have.

## What you get

**Less hallucination.** Agents search your docs before guessing. When the billing rules, API contracts, or architecture decisions are one tool call away, the agent uses them instead of making things up.

**Lower token costs.** A targeted search returns ~600 tokens of ranked snippets. Loading the same information by reading full files costs 3,000-8,000+ tokens. On a knowledge base with 170 docs (~840K tokens total), that's the difference between finding the right answer and blowing your context window.

**Docs that stay useful.** New docs are searchable the moment you ingest them. No manual routing tables to maintain, no hardcoded file paths to update. Agents discover docs dynamically through search, not through stale indexes.

**One search, full coverage.** Hybrid search combines keyword matching (tsvector) with semantic similarity (pgvector cosine). A query for "how does billing work" finds docs titled "Pricing Strategy" even when the word "billing" doesn't appear.

## Quick Start

```bash
pip install gnosis-mcp
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
gnosis-mcp init-db              # create tables + indexes
gnosis-mcp ingest ./docs/       # load your markdown
gnosis-mcp serve                # start MCP server
```

Or without installing:

```bash
uvx gnosis-mcp serve
```

### Connect your editor

**Claude Code** — add to `.claude/mcp.json`:

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

<details>
<summary>Cursor, Windsurf, Cline</summary>

Same JSON structure. Place it in:
- **Cursor**: `.cursor/mcp.json`
- **Windsurf**: `~/.codeium/windsurf/mcp_config.json`
- **Cline**: Cline MCP settings panel

</details>

## Claude Code Plugin

Install as a Claude Code plugin to get the MCP server, skills, and health check hook in one step:

```bash
claude plugin marketplace add nicholasglazer/gnosis-mcp
claude plugin install gnosis
```

This gives you:

| Component | What you get |
|-----------|-------------|
| **MCP server** | `gnosis-mcp serve` — auto-configured |
| **`/gnosis:search`** | Search docs with keyword or `--semantic` hybrid mode |
| **`/gnosis:status`** | Health check — connectivity, doc stats, troubleshooting |
| **`/gnosis:manage`** | CRUD — add, delete, update metadata, bulk embed |
| **SessionStart hook** | Verifies DB connectivity at session start |

You still need PostgreSQL and `pip install gnosis-mcp` for the server binary. The plugin wires everything into Claude Code automatically.

<details>
<summary>Manual setup (without plugin)</summary>

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "gnosis": {
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

## What It Does

Gnosis MCP provides 6 tools and 3 resources over MCP.

### Tools

| Tool | What it does | Mode |
|------|-------------|------|
| `search_docs` | Keyword or hybrid semantic+keyword search | Read |
| `get_doc` | Retrieve a full document by path | Read |
| `get_related` | Find linked documents | Read |
| `upsert_doc` | Create or replace a document | Write |
| `delete_doc` | Remove a document | Write |
| `update_metadata` | Change title, category, tags | Write |

Write tools require `GNOSIS_MCP_WRITABLE=true`. Read tools are always on.

### Resources

| URI | Returns |
|-----|---------|
| `gnosis://docs` | All documents — path, title, category, chunk count |
| `gnosis://docs/{path}` | Full document content |
| `gnosis://categories` | Categories with doc counts |

### Search

Three modes, one tool:

```bash
# Keyword — fast, exact matches
gnosis-mcp search "stripe webhook"

# Hybrid — keyword + semantic similarity
gnosis-mcp search "how does billing work" --embed

# Filtered — narrow by category
gnosis-mcp search "auth" -c guides
```

When called via MCP, pass `query_embedding` for hybrid mode. Without it, you get keyword search.

## Embeddings

Gnosis MCP handles embeddings in three tiers, all without adding dependencies:

**Accept pre-computed vectors** — pass `embeddings` to `upsert_doc` or `query_embedding` to `search_docs` if you generate them externally.

**Backfill with the CLI** — find chunks missing embeddings and fill them:

```bash
gnosis-mcp embed --dry-run              # see what needs embedding
gnosis-mcp embed                        # backfill via OpenAI (default)
gnosis-mcp embed --provider ollama      # or use local Ollama
```

Supports OpenAI, Ollama, and any OpenAI-compatible endpoint. Uses stdlib `urllib.request` — no new runtime deps.

**Built-in hybrid scoring** — when `query_embedding` is provided, search automatically combines keyword (tsvector) and cosine similarity using reciprocal rank fusion.

## Configuration

All settings via environment variables. Only `DATABASE_URL` is required.

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | *required* | PostgreSQL connection string |
| `GNOSIS_MCP_SCHEMA` | `public` | Database schema |
| `GNOSIS_MCP_CHUNKS_TABLE` | `documentation_chunks` | Chunks table name |
| `GNOSIS_MCP_SEARCH_FUNCTION` | — | Custom search function |
| `GNOSIS_MCP_EMBEDDING_DIM` | `1536` | Vector dimension for init-db |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable write tools |
| `GNOSIS_MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `sse` |

<details>
<summary>All 33 variables</summary>

**Search & chunking:** `GNOSIS_MCP_CONTENT_PREVIEW_CHARS` (200), `GNOSIS_MCP_CHUNK_SIZE` (4000), `GNOSIS_MCP_SEARCH_LIMIT_MAX` (20).

**Connection pool:** `GNOSIS_MCP_POOL_MIN` (1), `GNOSIS_MCP_POOL_MAX` (3).

**Webhooks:** `GNOSIS_MCP_WEBHOOK_URL`, `GNOSIS_MCP_WEBHOOK_TIMEOUT` (5s).

**Embeddings:** `GNOSIS_MCP_EMBED_PROVIDER` (openai/ollama/custom), `GNOSIS_MCP_EMBED_MODEL`, `GNOSIS_MCP_EMBED_API_KEY`, `GNOSIS_MCP_EMBED_URL`, `GNOSIS_MCP_EMBED_BATCH_SIZE` (50).

**Column overrides** (for existing tables with non-standard names): `GNOSIS_MCP_COL_FILE_PATH`, `GNOSIS_MCP_COL_TITLE`, `GNOSIS_MCP_COL_CONTENT`, `GNOSIS_MCP_COL_CHUNK_INDEX`, `GNOSIS_MCP_COL_CATEGORY`, `GNOSIS_MCP_COL_AUDIENCE`, `GNOSIS_MCP_COL_TAGS`, `GNOSIS_MCP_COL_EMBEDDING`, `GNOSIS_MCP_COL_TSV`, `GNOSIS_MCP_COL_SOURCE_PATH`, `GNOSIS_MCP_COL_TARGET_PATH`, `GNOSIS_MCP_COL_RELATION_TYPE`.

**Links table:** `GNOSIS_MCP_LINKS_TABLE` (documentation_links).

**Logging:** `GNOSIS_MCP_LOG_LEVEL` (INFO).

</details>

<details>
<summary>Custom search function</summary>

Delegate search to your own PostgreSQL function for custom ranking:

```sql
CREATE FUNCTION my_schema.my_search(
    p_query_text text,
    p_categories text[],
    p_limit integer
) RETURNS TABLE (
    file_path text, title text, content text,
    category text, combined_score double precision
) ...
```

```bash
GNOSIS_MCP_SEARCH_FUNCTION=my_schema.my_search
```

</details>

<details>
<summary>Multi-table mode</summary>

Query across multiple doc tables:

```bash
GNOSIS_MCP_CHUNKS_TABLE=documentation_chunks,api_docs,tutorial_chunks
```

All tables must share the same schema. Reads use `UNION ALL`. Writes target the first table.

</details>

## CLI Reference

```
gnosis-mcp serve [--transport stdio|sse] [--ingest PATH]   Start MCP server
gnosis-mcp init-db [--dry-run]                             Create tables + indexes
gnosis-mcp ingest <path> [--dry-run]                       Load markdown files
gnosis-mcp search <query> [-n LIMIT] [-c CAT] [--embed]    Search docs
gnosis-mcp embed [--provider P] [--model M] [--dry-run]    Backfill embeddings
gnosis-mcp stats                                           Document/chunk counts
gnosis-mcp export [-f json|markdown] [-c CAT]              Export documents
gnosis-mcp check                                           Verify DB connection
```

## Development

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 138 tests, no database needed
ruff check src/ tests/
```

## Architecture

```
src/gnosis_mcp/
├── config.py    Frozen dataclass, 33 env vars, SQL injection validation
├── db.py        asyncpg pool + FastMCP lifespan
├── server.py    FastMCP server — 6 tools, 3 resources, webhooks
├── ingest.py    Markdown scanner — H2 chunking, frontmatter, content hashing
├── schema.py    SQL templates — tables, indexes, search functions
├── embed.py     Embedding sidecar — provider abstraction, batch backfill
└── cli.py       CLI — serve, init-db, ingest, search, embed, stats, export, check
```

Design constraints: 2 runtime dependencies only (`mcp` + `asyncpg`). No pydantic, no click, no ORM. All SQL identifiers validated at startup. Write tools gated behind `cfg.writable`. Pure functions testable without a database.

## AI-Friendly Docs

| File | For |
|------|-----|
| [`llms.txt`](llms.txt) | Quick overview — tools, config, schema |
| [`llms-full.txt`](llms-full.txt) | Complete reference in one file |
| [`llms-install.md`](llms-install.md) | Step-by-step install guide |

## Contributing

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git && cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pytest
```

All tests run without a database. Keep it that way.

Good first contributions: new embedding providers, export formats, ingestion for RST/AsciiDoc/HTML, search highlighting. Open an issue first for larger changes.

## Sponsors

If Gnosis MCP saves you time, consider [sponsoring the project](https://github.com/sponsors/nicholasglazer).

## License

[MIT](LICENSE)
