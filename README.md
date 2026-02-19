<!-- mcp-name: io.github.nicholasglazer/gnosis -->
<div align="center">

<h1>Gnosis MCP</h1>

<p><strong>Give your AI agent a searchable knowledge base. Zero config.</strong></p>

<p>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/v/gnosis-mcp?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/pyversions/gnosis-mcp" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/actions"><img src="https://github.com/nicholasglazer/gnosis-mcp/actions/workflows/publish.yml/badge.svg" alt="CI"></a>
  <a href="https://registry.modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-Registry-blue" alt="MCP Registry"></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#choose-your-backend">Backends</a> &middot;
  <a href="#editor-integrations">Editor Setup</a> &middot;
  <a href="#what-it-does">Tools & Resources</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="llms-full.txt">Full Reference</a>
</p>

<a href="https://miozu.com/products/gnosis-mcp"><img src="https://miozu.com/oss/gnosis-mcp-demo.gif" alt="Gnosis MCP demo — ingest, search, serve" width="700"></a>

</div>

---

AI coding agents can read your source code but not your documentation. They guess at architecture, miss established patterns, and hallucinate details they could have looked up.

Gnosis MCP fixes this. Point it at a folder of markdown files and it creates a searchable knowledge base that any [MCP](https://modelcontextprotocol.io/)-compatible AI agent can query — Claude Code, Cursor, Windsurf, Cline, and any tool that supports the Model Context Protocol.

**No database server.** SQLite works out of the box with keyword search, or add `[embeddings]` for local semantic search. Scale to PostgreSQL + pgvector when needed.

## Why use this

**Less hallucination.** Agents search your docs before guessing. Architecture decisions, API contracts, billing rules — one tool call away instead of made up.

**Lower token costs.** A search returns ~600 tokens of ranked results. Reading the same docs as files costs 3,000-8,000+ tokens. On a 170-doc knowledge base (~840K tokens), that's the difference between a precise answer and a blown context window.

**Docs that stay current.** Add a new markdown file, run `ingest`, it's searchable immediately. Or use `--watch` to auto-re-ingest on file changes. No routing tables to maintain, no hardcoded paths to update.

**Works with what you have.** Your docs are already markdown files in a folder. Gnosis MCP indexes them as-is — no format conversion, no special syntax needed.

## Quick Start

```bash
pip install gnosis-mcp
gnosis-mcp ingest ./docs/       # loads markdown, auto-creates SQLite database
gnosis-mcp serve                # starts MCP server
```

That's it. Your AI agent can now search your docs.

**Want semantic search?** Add local ONNX embeddings (no API key needed, ~23MB model):

```bash
pip install gnosis-mcp[embeddings]
gnosis-mcp ingest ./docs/ --embed   # ingest + embed in one step
gnosis-mcp serve                    # hybrid keyword+semantic search auto-activated
```

Test it before connecting to an editor:

```bash
gnosis-mcp search "getting started"           # keyword search
gnosis-mcp search "how does auth work" --embed # hybrid semantic+keyword
gnosis-mcp stats                               # see what was indexed
```

<details>
<summary>Try without installing (uvx)</summary>

```bash
uvx gnosis-mcp ingest ./docs/
uvx gnosis-mcp serve
```

</details>

## Editor Integrations

Gnosis MCP works with any MCP-compatible editor. Add the server config, and your AI agent gets `search_docs`, `get_doc`, and `get_related` tools automatically.

### Claude Code

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

Or install as a [Claude Code plugin](#claude-code-plugin) for a richer experience with slash commands.

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
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
      "args": ["serve"]
    }
  }
}
```

### VS Code (GitHub Copilot)

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

Also discoverable via the VS Code MCP gallery — search `@mcp gnosis` in the Extensions view.

> **Enterprise:** Your org admin needs the "MCP servers in Copilot" policy enabled. Free/Pro/Pro+ plans work without this.

### JetBrains (IntelliJ, PyCharm, WebStorm)

Go to **Settings > Tools > AI Assistant > MCP Servers**, click **+**, and add:

- **Name:** `docs`
- **Command:** `gnosis-mcp`
- **Arguments:** `serve`

### Cline

Open Cline MCP settings panel and add the same server config.

### Other MCP clients

Any tool that supports the [Model Context Protocol](https://modelcontextprotocol.io/) works — including Zed, Neovim (via plugins), and custom agents. The server communicates over stdio by default, or SSE with `--transport sse`.

## Choose Your Backend

| | SQLite (default) | SQLite + embeddings | PostgreSQL |
|---|---|---|---|
| **Install** | `pip install gnosis-mcp` | `pip install gnosis-mcp[embeddings]` | `pip install gnosis-mcp[postgres]` |
| **Config** | Nothing | Nothing | Set `DATABASE_URL` |
| **Search** | FTS5 keyword (BM25) | Hybrid keyword + semantic (RRF) | tsvector + pgvector hybrid |
| **Embeddings** | None | Local ONNX (23MB, no API key) | Any provider + HNSW index |
| **Multi-table** | No | No | Yes (`UNION ALL`) |
| **Best for** | Quick start, keyword-only | Semantic search without a server | Production, large doc sets |

**Auto-detection:** Set `DATABASE_URL` to `postgresql://...` and it uses PostgreSQL. Don't set it and it uses SQLite. Override with `GNOSIS_MCP_BACKEND=sqlite|postgres`.

<details>
<summary>PostgreSQL setup</summary>

```bash
pip install gnosis-mcp[postgres]
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
gnosis-mcp init-db              # create tables + indexes
gnosis-mcp ingest ./docs/       # load your markdown
gnosis-mcp serve
```

For hybrid semantic+keyword search, also enable pgvector:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then backfill embeddings:

```bash
gnosis-mcp embed                        # via OpenAI (default)
gnosis-mcp embed --provider ollama      # or use local Ollama
```

</details>

## Claude Code Plugin

For Claude Code users, install as a plugin to get the MCP server plus slash commands:

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

The plugin works with both SQLite and PostgreSQL backends.

<details>
<summary>Manual setup (without plugin)</summary>

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

For PostgreSQL, add `"env": {"GNOSIS_MCP_DATABASE_URL": "postgresql://..."}`.

</details>

## What It Does

Gnosis MCP exposes 6 tools and 3 resources over MCP. Your AI agent calls these automatically when it needs information from your docs.

### Tools

| Tool | What it does | Mode |
|------|-------------|------|
| `search_docs` | Search by keyword or hybrid semantic+keyword | Read |
| `get_doc` | Retrieve a full document by path | Read |
| `get_related` | Find linked/related documents | Read |
| `upsert_doc` | Create or replace a document | Write |
| `delete_doc` | Remove a document and its chunks | Write |
| `update_metadata` | Change title, category, tags | Write |

Read tools are always available. Write tools require `GNOSIS_MCP_WRITABLE=true`.

### Resources

| URI | Returns |
|-----|---------|
| `gnosis://docs` | All documents — path, title, category, chunk count |
| `gnosis://docs/{path}` | Full document content |
| `gnosis://categories` | Categories with document counts |

### How search works

```bash
# Keyword search — works on both SQLite and PostgreSQL
gnosis-mcp search "stripe webhook"

# Hybrid search — keyword + semantic similarity (PostgreSQL + embeddings)
gnosis-mcp search "how does billing work" --embed

# Filtered — narrow results to a specific category
gnosis-mcp search "auth" -c guides
```

When called via MCP, the agent passes a `query` string for keyword search. On PostgreSQL with embeddings, it can also pass `query_embedding` for hybrid mode that combines keyword matching with semantic similarity.

## Embeddings

Embeddings enable semantic search — finding docs by meaning, not just keywords.

**1. Local ONNX (recommended for SQLite)** — zero-config, no API key needed:

```bash
pip install gnosis-mcp[embeddings]
gnosis-mcp ingest ./docs/ --embed       # ingest + embed in one step
gnosis-mcp embed                        # or embed existing chunks separately
```

Uses [MongoDB/mdbr-leaf-ir](https://huggingface.co/MongoDB/mdbr-leaf-ir) (~23MB quantized, Apache 2.0). Auto-downloads on first run. Customize with `GNOSIS_MCP_EMBED_MODEL`.

**2. Remote providers** — OpenAI, Ollama, or any OpenAI-compatible endpoint:

```bash
gnosis-mcp embed --provider openai      # requires GNOSIS_MCP_EMBED_API_KEY
gnosis-mcp embed --provider ollama      # uses local Ollama server
```

**3. Pre-computed vectors** — pass `embeddings` to `upsert_doc` or `query_embedding` to `search_docs` from your own pipeline.

**Hybrid search** — when embeddings are available, search automatically combines keyword (BM25) and semantic (cosine) results using Reciprocal Rank Fusion (RRF). Works on both SQLite (via sqlite-vec) and PostgreSQL (via pgvector).

## Configuration

All settings via environment variables. Nothing required for SQLite — it works with zero config.

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | SQLite auto | PostgreSQL URL or SQLite file path |
| `GNOSIS_MCP_BACKEND` | `auto` | Force `sqlite` or `postgres` |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable write tools (`upsert_doc`, `delete_doc`, `update_metadata`) |
| `GNOSIS_MCP_TRANSPORT` | `stdio` | Server transport: `stdio` or `sse` |
| `GNOSIS_MCP_SCHEMA` | `public` | Database schema (PostgreSQL only) |
| `GNOSIS_MCP_CHUNKS_TABLE` | `documentation_chunks` | Table name for chunks |
| `GNOSIS_MCP_SEARCH_FUNCTION` | — | Custom search function (PostgreSQL only) |
| `GNOSIS_MCP_EMBEDDING_DIM` | `1536` | Vector dimension for init-db |

<details>
<summary>All variables</summary>

**Search & chunking:** `GNOSIS_MCP_CONTENT_PREVIEW_CHARS` (200), `GNOSIS_MCP_CHUNK_SIZE` (4000), `GNOSIS_MCP_SEARCH_LIMIT_MAX` (20).

**Connection pool (PostgreSQL):** `GNOSIS_MCP_POOL_MIN` (1), `GNOSIS_MCP_POOL_MAX` (3).

**Webhooks:** `GNOSIS_MCP_WEBHOOK_URL`, `GNOSIS_MCP_WEBHOOK_TIMEOUT` (5s). Set a URL to receive POST notifications when documents are created, updated, or deleted.

**Embeddings:** `GNOSIS_MCP_EMBED_PROVIDER` (openai/ollama/custom/local), `GNOSIS_MCP_EMBED_MODEL` (text-embedding-3-small for remote, MongoDB/mdbr-leaf-ir for local), `GNOSIS_MCP_EMBED_DIM` (384, Matryoshka truncation dimension for local provider), `GNOSIS_MCP_EMBED_API_KEY`, `GNOSIS_MCP_EMBED_URL` (custom endpoint), `GNOSIS_MCP_EMBED_BATCH_SIZE` (50).

**Column overrides** (for connecting to existing tables with non-standard column names): `GNOSIS_MCP_COL_FILE_PATH`, `GNOSIS_MCP_COL_TITLE`, `GNOSIS_MCP_COL_CONTENT`, `GNOSIS_MCP_COL_CHUNK_INDEX`, `GNOSIS_MCP_COL_CATEGORY`, `GNOSIS_MCP_COL_AUDIENCE`, `GNOSIS_MCP_COL_TAGS`, `GNOSIS_MCP_COL_EMBEDDING`, `GNOSIS_MCP_COL_TSV`, `GNOSIS_MCP_COL_SOURCE_PATH`, `GNOSIS_MCP_COL_TARGET_PATH`, `GNOSIS_MCP_COL_RELATION_TYPE`.

**Links table:** `GNOSIS_MCP_LINKS_TABLE` (documentation_links).

**Logging:** `GNOSIS_MCP_LOG_LEVEL` (INFO).

</details>

<details>
<summary>Custom search function (PostgreSQL)</summary>

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
<summary>Multi-table mode (PostgreSQL)</summary>

Query across multiple doc tables:

```bash
GNOSIS_MCP_CHUNKS_TABLE=documentation_chunks,api_docs,tutorial_chunks
```

All tables must share the same schema. Reads use `UNION ALL`. Writes target the first table.

</details>

## CLI Reference

```
gnosis-mcp ingest <path> [--dry-run] [--embed]             Load markdown files (--embed to generate embeddings)
gnosis-mcp serve [--transport stdio|sse] [--ingest PATH] [--watch PATH]   Start MCP server (--watch for live reload)
gnosis-mcp search <query> [-n LIMIT] [-c CAT] [--embed]    Search (--embed for hybrid semantic+keyword)
gnosis-mcp stats                                           Show document, chunk, and embedding counts
gnosis-mcp check                                           Verify database connection + sqlite-vec status
gnosis-mcp embed [--provider P] [--model M] [--dry-run]    Backfill embeddings (auto-detects local provider)
gnosis-mcp init-db [--dry-run]                             Create tables + indexes manually
gnosis-mcp export [-f json|markdown] [-c CAT]              Export documents
```

## How ingestion works

`gnosis-mcp ingest` scans a directory for `.md` files and loads them into the database:

- **Smart chunking** — splits by H2 headings, keeping sections together (not arbitrary character limits)
- **Frontmatter support** — extracts `title`, `category`, `audience`, `tags` from YAML frontmatter
- **Auto-categorization** — infers category from the parent directory name
- **Incremental updates** — content hashing skips unchanged files on re-run
- **Watch mode** — `gnosis-mcp serve --watch ./docs/` auto-re-ingests on file changes
- **Dry run** — preview what would be indexed with `--dry-run`

## Available on

Gnosis MCP is listed on the [Official MCP Registry](https://registry.modelcontextprotocol.io) (which feeds the VS Code MCP gallery and GitHub Copilot), [PyPI](https://pypi.org/project/gnosis-mcp/), and major MCP directories including [mcp.so](https://mcp.so), [Glama](https://glama.ai), and [cursor.directory](https://cursor.directory).

## Architecture

```
src/gnosis_mcp/
├── backend.py         DocBackend protocol + create_backend() factory
├── pg_backend.py      PostgreSQL — asyncpg, tsvector, pgvector
├── sqlite_backend.py  SQLite — aiosqlite, FTS5, sqlite-vec hybrid search (RRF)
├── sqlite_schema.py   SQLite DDL — tables, FTS5, triggers, vec0 virtual table
├── config.py          Config from env vars, backend auto-detection
├── db.py              Backend lifecycle + FastMCP lifespan
├── server.py          FastMCP server — 6 tools, 3 resources, auto-embed queries
├── ingest.py          Markdown scanner — H2 chunking, frontmatter
├── watch.py           File watcher — mtime polling, auto-re-ingest on changes
├── schema.py          PostgreSQL DDL — tables, indexes, search functions
├── embed.py           Embedding providers — OpenAI, Ollama, custom, local ONNX
├── local_embed.py     Local ONNX embedding engine — HuggingFace model download
└── cli.py             CLI — serve, ingest, search, embed, stats, check
```

## AI-Friendly Docs

These files are optimized for AI agents to consume:

| File | Purpose |
|------|---------|
| [`llms.txt`](llms.txt) | Quick overview — what it does, tools, config |
| [`llms-full.txt`](llms-full.txt) | Complete reference in one file |
| [`llms-install.md`](llms-install.md) | Step-by-step installation guide |

## Development

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 220+ tests, no database needed
ruff check src/ tests/
```

All tests run without a database. Keep it that way.

Good first contributions: new embedding providers, export formats, ingestion for RST/AsciiDoc/HTML, search highlighting. Open an issue first for larger changes.

## Sponsors

If Gnosis MCP saves you time, consider [sponsoring the project](https://github.com/sponsors/nicholasglazer).

## License

[MIT](LICENSE)
