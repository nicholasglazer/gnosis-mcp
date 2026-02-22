<!-- mcp-name: io.github.nicholasglazer/gnosis -->
<div align="center">

<h1>Gnosis MCP</h1>

<p><strong>Turn your docs into a searchable knowledge base for AI agents.<br>pip install, ingest, serve.</strong></p>

<p>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/v/gnosis-mcp?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/dm/gnosis-mcp?color=green" alt="Downloads"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/pyversions/gnosis-mcp" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/actions"><img src="https://github.com/nicholasglazer/gnosis-mcp/actions/workflows/publish.yml/badge.svg" alt="CI"></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#web-crawl">Web Crawl</a> &middot;
  <a href="#backends">Backends</a> &middot;
  <a href="#editor-integrations">Editors</a> &middot;
  <a href="#tools--resources">Tools</a> &middot;
  <a href="#embeddings">Embeddings</a> &middot;
  <a href="llms-full.txt">Full Reference</a>
</p>

<a href="#quick-start"><img src="https://raw.githubusercontent.com/nicholasglazer/gnosis-mcp/main/demo-hero.gif" alt="Gnosis MCP — ingest docs, search, view stats, serve" width="700"></a>
<br>
<sub>Ingest docs &rarr; Search with highlights &rarr; Stats overview &rarr; Serve to AI agents</sub>

</div>

---

### Without a docs server

- LLMs hallucinate API signatures that don't exist
- Entire files dumped into context — 3,000 to 8,000+ tokens each
- Architecture decisions buried across dozens of files

### With Gnosis MCP

- `search_docs` returns ranked, highlighted excerpts (~600 tokens)
- Real answers grounded in your actual documentation
- Works across hundreds of docs instantly

---

## Features

- **Zero config** — SQLite by default, `pip install` and go
- **Hybrid search** — keyword (BM25) + semantic (local ONNX embeddings, no API key)
- **Web crawl** — ingest documentation from any website via sitemap or link crawl
- **Multi-format** — `.md` `.txt` `.ipynb` `.toml` `.csv` `.json` + optional `.rst` `.pdf`
- **Auto-linking** — `relates_to` frontmatter creates a navigable document graph
- **Watch mode** — auto-re-ingest on file changes
- **PostgreSQL ready** — pgvector + tsvector when you need scale

## Quick Start

```bash
pip install gnosis-mcp
gnosis-mcp ingest ./docs/       # loads docs into SQLite (auto-created)
gnosis-mcp serve                # starts MCP server
```

That's it. Your AI agent can now search your docs.

**Want semantic search?** Add local embeddings — no API key needed:

```bash
pip install gnosis-mcp[embeddings]
gnosis-mcp ingest ./docs/ --embed   # ingest + embed in one step
gnosis-mcp serve                    # hybrid search auto-activated
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

## Web Crawl

<div align="center">
<img src="https://raw.githubusercontent.com/nicholasglazer/gnosis-mcp/main/demo-crawl.gif" alt="Gnosis MCP — crawl docs with dry-run, fetch, search, SSRF protection" width="700">
<br>
<sub>Dry-run discovery &rarr; Crawl &amp; ingest &rarr; Search crawled docs &rarr; SSRF protection</sub>
</div>

<br>

Ingest docs from any website — no local files needed:

```bash
pip install gnosis-mcp[web]

# Crawl via sitemap (best for large doc sites)
gnosis-mcp crawl https://docs.stripe.com/ --sitemap

# Depth-limited link crawl with URL filter
gnosis-mcp crawl https://fastapi.tiangolo.com/ --depth 2 --include "/tutorial/*"

# Preview what would be crawled
gnosis-mcp crawl https://docs.python.org/ --dry-run

# Force re-crawl + embed for semantic search
gnosis-mcp crawl https://docs.sveltekit.dev/ --sitemap --force --embed
```

Respects `robots.txt`, caches with ETag/Last-Modified for incremental re-crawl, and rate-limits requests (5 concurrent, 0.2s delay). Crawled pages use the URL as the document path and hostname as the category — searchable like any other doc.

## Editor Integrations

Add the server config to your editor — your AI agent gets `search_docs`, `get_doc`, and `get_related` tools automatically:

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

| Editor | Config file |
|--------|------------|
| **Claude Code** | `.claude/mcp.json` (or [install as plugin](#claude-code-plugin)) |
| **Cursor** | `.cursor/mcp.json` |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` |
| **JetBrains** | Settings > Tools > AI Assistant > MCP Servers |
| **Cline** | Cline MCP settings panel |

<details>
<summary>VS Code (GitHub Copilot) — slightly different key</summary>

Add to `.vscode/mcp.json` (note: `"servers"` not `"mcpServers"`):

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

</details>

For remote deployment, use Streamable HTTP:

```bash
gnosis-mcp serve --transport streamable-http --host 0.0.0.0 --port 8000
```

## Backends

| | SQLite (default) | SQLite + embeddings | PostgreSQL |
|---|---|---|---|
| **Install** | `pip install gnosis-mcp` | `pip install gnosis-mcp[embeddings]` | `pip install gnosis-mcp[postgres]` |
| **Config** | Nothing | Nothing | Set `GNOSIS_MCP_DATABASE_URL` |
| **Search** | FTS5 keyword (BM25) | Hybrid keyword + semantic (RRF) | tsvector + pgvector hybrid |
| **Embeddings** | None | Local ONNX (23MB, no API key) | Any provider + HNSW index |
| **Multi-table** | No | No | Yes (`UNION ALL`) |
| **Best for** | Quick start, keyword-only | Semantic search without a server | Production, large doc sets |

**Auto-detection:** Set `GNOSIS_MCP_DATABASE_URL` to `postgresql://...` and it uses PostgreSQL. Don't set it and it uses SQLite. Override with `GNOSIS_MCP_BACKEND=sqlite|postgres`.

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

## Tools & Resources

Gnosis MCP exposes 6 tools and 3 resources over [MCP](https://modelcontextprotocol.io/). Your AI agent calls these automatically when it needs information from your docs.

| Tool | What it does | Mode |
|------|-------------|------|
| `search_docs` | Search by keyword or hybrid semantic+keyword | Read |
| `get_doc` | Retrieve a full document by path | Read |
| `get_related` | Find linked/related documents | Read |
| `upsert_doc` | Create or replace a document | Write |
| `delete_doc` | Remove a document and its chunks | Write |
| `update_metadata` | Change title, category, tags | Write |

Read tools are always available. Write tools require `GNOSIS_MCP_WRITABLE=true`.

| Resource URI | Returns |
|-----|---------|
| `gnosis://docs` | All documents — path, title, category, chunk count |
| `gnosis://docs/{path}` | Full document content |
| `gnosis://categories` | Categories with document counts |

### How search works

```bash
# Keyword search — works on both SQLite and PostgreSQL
gnosis-mcp search "stripe webhook"

# Hybrid search — keyword + semantic (requires [embeddings] or pgvector)
gnosis-mcp search "how does billing work" --embed

# Filtered — narrow results to a specific category
gnosis-mcp search "auth" -c guides
```

When called via MCP, the agent passes a `query` string for keyword search. With embeddings configured, search automatically combines keyword and semantic results using Reciprocal Rank Fusion. Results include a `highlight` field with matched terms in `<mark>` tags.

## Embeddings

Embeddings enable semantic search — finding docs by meaning, not just keywords.

**Local ONNX (recommended)** — zero-config, no API key:

```bash
pip install gnosis-mcp[embeddings]
gnosis-mcp ingest ./docs/ --embed       # ingest + embed in one step
gnosis-mcp embed                        # or embed existing chunks separately
```

Uses [MongoDB/mdbr-leaf-ir](https://huggingface.co/MongoDB/mdbr-leaf-ir) (~23MB quantized, Apache 2.0). Auto-downloads on first run.

**Remote providers** — OpenAI, Ollama, or any OpenAI-compatible endpoint:

```bash
gnosis-mcp embed --provider openai      # requires GNOSIS_MCP_EMBED_API_KEY
gnosis-mcp embed --provider ollama      # uses local Ollama server
```

**Pre-computed vectors** — pass `embeddings` to `upsert_doc` or `query_embedding` to `search_docs` from your own pipeline.

## Configuration

All settings via environment variables. Nothing required for SQLite — it works with zero config.

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | SQLite auto | PostgreSQL URL or SQLite file path |
| `GNOSIS_MCP_BACKEND` | `auto` | Force `sqlite` or `postgres` |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable write tools |
| `GNOSIS_MCP_TRANSPORT` | `stdio` | Transport: `stdio`, `sse`, or `streamable-http` |
| `GNOSIS_MCP_EMBEDDING_DIM` | `1536` | Vector dimension for init-db |

<details>
<summary>All configuration variables</summary>

**Database:** `GNOSIS_MCP_SCHEMA` (public), `GNOSIS_MCP_CHUNKS_TABLE` (documentation_chunks), `GNOSIS_MCP_LINKS_TABLE` (documentation_links), `GNOSIS_MCP_SEARCH_FUNCTION` (custom search on PG).

**Search & chunking:** `GNOSIS_MCP_CONTENT_PREVIEW_CHARS` (200), `GNOSIS_MCP_CHUNK_SIZE` (4000), `GNOSIS_MCP_SEARCH_LIMIT_MAX` (20).

**Connection pool (PostgreSQL):** `GNOSIS_MCP_POOL_MIN` (1), `GNOSIS_MCP_POOL_MAX` (3).

**Webhooks:** `GNOSIS_MCP_WEBHOOK_URL`, `GNOSIS_MCP_WEBHOOK_TIMEOUT` (5s).

**Embeddings:** `GNOSIS_MCP_EMBED_PROVIDER` (openai/ollama/custom/local), `GNOSIS_MCP_EMBED_MODEL`, `GNOSIS_MCP_EMBED_DIM` (384), `GNOSIS_MCP_EMBED_API_KEY`, `GNOSIS_MCP_EMBED_URL`, `GNOSIS_MCP_EMBED_BATCH_SIZE` (50).

**Column overrides:** `GNOSIS_MCP_COL_FILE_PATH`, `GNOSIS_MCP_COL_TITLE`, `GNOSIS_MCP_COL_CONTENT`, `GNOSIS_MCP_COL_CHUNK_INDEX`, `GNOSIS_MCP_COL_CATEGORY`, `GNOSIS_MCP_COL_AUDIENCE`, `GNOSIS_MCP_COL_TAGS`, `GNOSIS_MCP_COL_EMBEDDING`, `GNOSIS_MCP_COL_TSV`, `GNOSIS_MCP_COL_SOURCE_PATH`, `GNOSIS_MCP_COL_TARGET_PATH`, `GNOSIS_MCP_COL_RELATION_TYPE`.

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

<details>
<summary>CLI reference</summary>

```
gnosis-mcp ingest <path> [--dry-run] [--force] [--embed]    Load files into database
gnosis-mcp crawl <url> [--sitemap] [--depth N] [--include] [--exclude] [--dry-run] [--force] [--embed]
gnosis-mcp serve [--transport stdio|sse|streamable-http] [--ingest PATH] [--watch PATH]
gnosis-mcp search <query> [-n LIMIT] [-c CAT] [--embed]    Search docs
gnosis-mcp stats                                           Document, chunk, and embedding counts
gnosis-mcp check                                           Verify DB connection + sqlite-vec
gnosis-mcp embed [--provider P] [--model M] [--dry-run]    Backfill embeddings
gnosis-mcp init-db [--dry-run]                             Create tables + indexes
gnosis-mcp export [-f json|markdown|csv] [-c CAT]          Export documents
gnosis-mcp diff <path>                                     Preview changes on re-ingest
```

</details>

<details>
<summary>How ingestion works</summary>

`gnosis-mcp ingest` scans a directory for supported files and loads them into the database:

- **Multi-format** — Markdown native; `.txt`, `.ipynb`, `.toml`, `.csv`, `.json` auto-converted. Optional: `.rst` (`[rst]` extra), `.pdf` (`[pdf]` extra)
- **Smart chunking** — splits by H2 headings (H3/H4 for oversized sections), never splits inside code blocks or tables
- **Frontmatter** — extracts `title`, `category`, `audience`, `tags` from YAML frontmatter
- **Auto-linking** — `relates_to` in frontmatter creates bidirectional links for `get_related`
- **Auto-categorization** — infers category from parent directory name
- **Incremental** — content hashing skips unchanged files (`--force` to override)
- **Watch mode** — `gnosis-mcp serve --watch ./docs/` auto-re-ingests on changes

</details>

<details>
<summary>Architecture</summary>

```
src/gnosis_mcp/
├── backend.py         DocBackend protocol + create_backend() factory
├── pg_backend.py      PostgreSQL — asyncpg, tsvector, pgvector
├── sqlite_backend.py  SQLite — aiosqlite, FTS5, sqlite-vec hybrid search (RRF)
├── sqlite_schema.py   SQLite DDL — tables, FTS5, triggers, vec0 virtual table
├── config.py          Config from env vars, backend auto-detection
├── db.py              Backend lifecycle + FastMCP lifespan
├── server.py          FastMCP server — 6 tools, 3 resources, auto-embed queries
├── ingest.py          File scanner + converters — multi-format, smart chunking
├── crawl.py           Web crawler — sitemap/BFS, robots.txt, ETag caching
├── watch.py           File watcher — mtime polling, auto-re-ingest
├── schema.py          PostgreSQL DDL — tables, indexes, search functions
├── embed.py           Embedding providers — OpenAI, Ollama, custom, local ONNX
├── local_embed.py     Local ONNX embedding engine — HuggingFace model download
└── cli.py             CLI — serve, ingest, crawl, search, embed, stats, check
```

</details>

## Available On

[MCP Registry](https://registry.modelcontextprotocol.io) (feeds VS Code MCP gallery and GitHub Copilot) · [PyPI](https://pypi.org/project/gnosis-mcp/) · [mcp.so](https://mcp.so) · [Glama](https://glama.ai) · [cursor.directory](https://cursor.directory)

## AI-Friendly Docs

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
pytest                    # 470+ tests, no database needed
ruff check src/ tests/
```

All tests run without a database. Keep it that way.

Good first contributions: new embedding providers, export formats, ingestion for new file types (via optional extras). Open an issue first for larger changes.

## Sponsors

If Gnosis MCP saves you time, consider [sponsoring the project](https://github.com/sponsors/nicholasglazer).

## License

[MIT](LICENSE)
