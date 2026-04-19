<!-- mcp-name: io.github.nicholasglazer/gnosis -->
<div align="center">

<h1>Gnosis MCP</h1>

<p><strong>Stop pasting files into context. Your AI agent searches your local docs instead.<br>5–10× fewer tokens per lookup. 92 % Hit@5 on real dev docs. Zero cloud dependencies.</strong></p>

<p>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/v/gnosis-mcp?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/dm/gnosis-mcp?color=green" alt="Downloads"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/pyversions/gnosis-mcp" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/actions"><img src="https://github.com/nicholasglazer/gnosis-mcp/actions/workflows/publish.yml/badge.svg" alt="CI"></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#git-history">Git History</a> &middot;
  <a href="#web-crawl">Web Crawl</a> &middot;
  <a href="#backends">Backends</a> &middot;
  <a href="#editor-integrations">Editors</a> &middot;
  <a href="#tools--resources">Tools</a> &middot;
  <a href="#embeddings">Embeddings</a> &middot;
  <a href="llms-full.txt">Full Reference</a>
</p>

<a href="#quick-start"><img src="https://raw.githubusercontent.com/nicholasglazer/gnosis-mcp/main/demo/demo-hero.gif" alt="Gnosis MCP — ingest docs, search, view stats, serve" width="700"></a>
<br>
<sub>Ingest docs &rarr; Search with highlights &rarr; Stats overview &rarr; Serve to AI agents</sub>

</div>

---

### Without a docs server

- LLMs hallucinate API signatures that don't exist
- Entire files dumped into context — 3,000–15,000 tokens per doc
- Architecture decisions buried across dozens of files
- Every repeated lookup pays full context cost

### With Gnosis MCP

- `search_docs` returns ranked, highlighted excerpts — typically 300–800 tokens
- Real answers grounded in your actual docs, not guesses from training data
- One local index across hundreds of files — instant multi-doc search
- **5–10× token savings** per lookup when your corpus covers the question

---

## What makes gnosis-mcp different

- **Your data stays on your machine.** SQLite by default, PostgreSQL at scale — nothing leaves the host.
- **Index anything that's docs-shaped.** Markdown, git commit history, crawled websites — one index, one search API.
- **Measured, not marketed.** Ships BEIR SciFact numbers (0.671 nDCG@10 — within 1 % of the Lucene BM25 baseline), a reproducible eval harness (`gnosis-mcp eval`), and a chunk-size sweep showing where the quality plateau actually sits.

Full side-by-side vs Context7 / docs-mcp-server / mcp-local-rag: [gnosismcp.com#compare](https://gnosismcp.com/#compare).

---

## Features

- **Zero config** — SQLite by default, `pip install` and go
- **Hybrid search** — keyword (BM25) + semantic (local ONNX embeddings, no API key). Tune RRF fusion with `GNOSIS_MCP_RRF_K`.
- **Cross-encoder reranking** — optional `[reranking]` extra with a 22M-param ONNX model. Off by default. **[Test on your own corpus before enabling](docs/bench-experiments-2026-04-18.md)** — the bundled MS-MARCO reranker hurts dev-doc retrieval in our measurements.
- **Git history** — ingest commit messages as searchable context (`ingest-git`)
- **Web crawl** — ingest documentation from any website via sitemap or link crawl
- **Multi-format** — `.md` `.txt` `.ipynb` `.toml` `.csv` `.json` + optional `.rst` `.pdf`
- **Auto-linking** — `relates_to` frontmatter creates a navigable document graph
- **Watch mode** — auto-re-ingest on file changes
- **Prune stale docs** — `gnosis-mcp ingest --prune` removes chunks whose source file was deleted. `--wipe` for a full reset before re-ingest.
- **Built-in eval harness** — `gnosis-mcp eval` prints Hit@K / MRR / Precision@K in one command
- **PostgreSQL ready** — pgvector + tsvector when you need scale

## Performance

**Fast.** 8.7 ms mean MCP round-trip. Hybrid search p50 < 30 ms on a 700-doc corpus. Keyword QPS scales from 9,463 @ 100 docs to 471 @ 10,000 docs ([full numbers](https://gnosismcp.com/#numbers)).

**Finds the right answer.** On 558 real dev docs with 25 hand-written golden queries: Hit@5 = **0.92**, nDCG@10 = **0.87**, MRR = **0.79**. On BEIR SciFact (5,183 docs, public retrieval benchmark): nDCG@10 = **0.671** — within 1 % of the Lucene BM25 baseline.

**Tokens saved.** Each `search_docs` call returns 200–500 tokens of on-point snippets instead of the 3,000–15,000 tokens a full-file Read would have cost. Track your own with `gnosis-mcp savings` (v0.12.0+) — the ledger writes to `search_access_log` on every call and aggregates per tool per `--days N`:

```
$ gnosis-mcp savings --days 7
  Tool calls:               142
  Tokens returned:        7,104
  Tokens baseline:      231,580
  Tokens saved:         224,476
  Ratio:                   32.6×
```

Typical compression runs 10–60× depending on corpus coverage and query specificity — verify on yours. `access_log` is on by default; `GNOSIS_MCP_ACCESS_LOG=false` opts out.

**Reproducible.** `gnosis-mcp eval` runs a RAG eval harness locally in one second. `tests/bench/*.py` reproduce every number. Methodology: [`docs/benchmarks.md`](docs/benchmarks.md).

**Rerankers stay off by default.** The bundled MS-MARCO cross-encoder drops nDCG@10 by 27 points on dev-docs and adds 400× latency; BGE-reranker-v2-m3 drops it 31 points at 2400×. Test on your corpus before enabling — full write-up: [bench-experiments-2026-04-18](docs/bench-experiments-2026-04-18.md).

## Quick Start

```bash
pip install gnosis-mcp           # or: uv tool install gnosis-mcp
gnosis-mcp ingest ./docs/        # loads docs into SQLite (auto-created)
gnosis-mcp serve                 # starts MCP server
```

That's it. Your AI agent can now search your docs.

**Connect your editor** — see [`llms-install.md`](llms-install.md) for copy-paste JSON snippets for Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, JetBrains, and Cline.

**Re-organized your docs?** `gnosis-mcp ingest ./docs --prune` re-ingests and removes any DB chunk whose source file no longer exists. `--wipe` resets the entire index first. Or run `gnosis-mcp prune ./docs --dry-run` to preview what would be deleted.

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
<summary>Run with Docker (zero install)</summary>

Multi-arch image, ~140 MB, ships with local ONNX embeddings + REST:

```bash
# Serve your ./docs on http://localhost:8000 — MCP at /mcp, REST at /api/*
docker run -p 8000:8000 \
  -v "$PWD/docs:/docs:ro" -v gnosis-data:/data \
  ghcr.io/nicholasglazer/gnosis-mcp:latest

# First-run: ingest into the persistent volume
docker run --rm \
  -v "$PWD/docs:/docs:ro" -v gnosis-data:/data \
  ghcr.io/nicholasglazer/gnosis-mcp:latest \
  ingest /docs --embed
```

Or use the committed [`docker-compose.yaml`](docker-compose.yaml):

```bash
docker compose up -d
docker compose exec gnosis gnosis-mcp ingest /docs --embed
```

Images tagged `:latest`, `:<version>`, `:<version-minor>`, `:main`, `:sha-<sha>`.

</details>

<details>
<summary>Try without installing (uvx)</summary>

```bash
uvx gnosis-mcp ingest ./docs/
uvx gnosis-mcp serve
```

</details>

## Web Crawl

<div align="center">
<img src="https://raw.githubusercontent.com/nicholasglazer/gnosis-mcp/main/demo/demo-crawl.gif" alt="Gnosis MCP — crawl docs with dry-run, fetch, search, SSRF protection" width="700">
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

## Git History

Turn commit messages into searchable context — your agent learns *why* things were built, not just *what* exists:

```bash
gnosis-mcp ingest-git .                                  # current repo, all files
gnosis-mcp ingest-git /path/to/repo --since 6m           # last 6 months only
gnosis-mcp ingest-git . --include "src/*" --max-commits 5 # filtered + limited
gnosis-mcp ingest-git . --dry-run                         # preview without ingesting
gnosis-mcp ingest-git . --embed                           # embed for semantic search
```

Each file's commit history becomes a searchable markdown document stored as `git-history/<file-path>`. The agent finds it via `search_docs` like any other doc — no new tools needed. Incremental re-ingest skips files with unchanged history.

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

## Transport

Stdio (default) spawns one server per editor session — simplest. HTTP shares one process across every client so the DB, embedding cache, and file watcher stay in sync across sessions:

```bash
gnosis-mcp serve --transport streamable-http --host 0.0.0.0 --port 8000
```

```json
{ "mcpServers": { "docs": { "type": "url", "url": "http://127.0.0.1:8000/mcp" } } }
```

Pick HTTP for multi-session agent setups (Claude Code with agent teams, parallel terminals, CI). Full write-up: **[gnosismcp.com/doc/docs/deployment](https://gnosismcp.com/doc/docs/deployment)**.

## REST API

> v0.10.0+ — HTTP endpoints alongside MCP on the same port.

```bash
gnosis-mcp serve --transport streamable-http --rest
```

| Endpoint | Returns |
|----------|---------|
| `GET /health` | status, version, distinct-doc + chunk counts |
| `GET /api/search?q=` | hybrid search (auto-embeds with `local` provider) |
| `GET /api/docs/{path}` | full document |
| `GET /api/docs/{path}/related` | graph neighbours |
| `GET /api/categories` | category → doc count |
| `GET /api/context?topic=` | usage-weighted topic primer |
| `GET /api/graph/stats` | orphans, hubs, relation distribution |

CORS, Bearer auth, custom public-path allowlist — full reference: **[`docs/rest-api.md`](docs/rest-api.md)** · **[gnosismcp.com/doc/docs/rest-api](https://gnosismcp.com/doc/docs/rest-api)**.

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
| **MCP server** | `gnosis-mcp serve` — auto-configured, search tools in every chat |
| **`/gnosis:setup`** | First-time wizard: install → init-db → ingest → wire your editor |
| **`/gnosis:ingest`** | Bulk ingest (files, git history, web crawl) + re-ingest + prune |
| **`/gnosis:search`** | Keyword / hybrid / git-history search, formatted output |
| **`/gnosis:manage`** | Single-file CRUD — add, delete, update metadata |
| **`/gnosis:tune`** | Chunk-size sweep against your own golden queries |
| **`/gnosis:eval`** | Single-shot retrieval quality check with baseline tracking |
| **`/gnosis:context`** | Usage-weighted topic primer for session startup |
| **`/gnosis:status`** | Connectivity, schema, corpus health diagnostic |
| 5 subagents | `doc-explorer`, `doc-keeper`, `corpus-sync`, `context-loader`, `doc-reviewer` |

The plugin works with both SQLite and PostgreSQL backends. Prefer manual copy-paste over the plugin marketplace? See [`llms-install.md`](llms-install.md) Path B.

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

Gnosis MCP exposes 9 tools and 3 resources over [MCP](https://modelcontextprotocol.io/). Your AI agent calls these automatically when it needs information from your docs.

| Tool | What it does | Mode |
|------|-------------|------|
| `search_docs` | Search by keyword or hybrid semantic+keyword | Read |
| `get_doc` | Retrieve a full document by path | Read |
| `get_related` | Find linked/related documents (multi-hop, relation type filtering) | Read |
| `search_git_history` | Search indexed git commit history | Read |
| `get_context` | Usage-weighted context summary | Read |
| `get_graph_stats` | Knowledge graph topology: orphans, hubs, relation distribution | Read |
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

### Context Loading

The `get_context` tool provides usage-weighted document summaries — ideal for session startup or "what matters most?" queries.

```bash
# Most-accessed docs (no topic)
get_context(limit=10)

# Topic-focused with access enrichment
get_context(topic="deployment", category="guides")
```

Behind the scenes, Gnosis tracks which documents are accessed via `search_docs` and `get_doc`, then uses access frequency to rank importance. Disable tracking with `GNOSIS_MCP_ACCESS_LOG=false`.

### Graph & Links

Gnosis automatically extracts links from your documentation — both frontmatter `relates_to` declarations and markdown links in content. Use the graph tools to explore connections:

```bash
# Direct neighbors
get_related("guides/auth.md")

# Multi-hop traversal (2 levels deep, with titles)
get_related("guides/auth.md", depth=2, include_titles=True)

# Filter out noisy git history links
get_related("guides/auth.md", relation_type="relates_to")

# Graph topology: find orphans and hubs
get_graph_stats()
```

**Relation types:** `related` (default frontmatter), `content_link` (body markdown links + `[[wikilinks]]`), `git_co_change` (commit co-occurrence), `git_ref` (git history → source file). Plus 16 typed edges via the `relations:` frontmatter block: `prerequisite`, `depends_on`, `summarizes` / `summarized_by`, `extends` / `extended_by`, `replaces` / `replaced_by`, `audited_by` / `audits`, `implements` / `implemented_by`, `tests` / `tested_by`, `example_of`, `references`.

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

Nothing required for SQLite — zero config works. Override via `GNOSIS_MCP_*` env vars. Most-used:

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | SQLite auto | PostgreSQL URL or SQLite file path |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable `upsert_doc` / `delete_doc` / `update_metadata` |
| `GNOSIS_MCP_EMBED_PROVIDER` | unset | `local` turns on hybrid search (needs `[embeddings]` extra) |
| `GNOSIS_MCP_COLLAPSE_BY_DOC` | `false` | Dedup top-K by file_path (+2 nDCG on mixed corpora) |
| `GNOSIS_MCP_RERANK_ENABLED` | `false` | Cross-encoder rerank — **test first**, hurts dev-docs |

Full list (~40 variables covering embeddings, crawl, REST, column overrides, webhooks, logging): **[`docs/config.md`](docs/config.md)** · browsable at **[gnosismcp.com/doc/docs/config](https://gnosismcp.com/doc/docs/config)**.

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
gnosis-mcp ingest <path> [--dry-run] [--force] [--embed] [--prune] [--wipe] [--include-crawled]
gnosis-mcp ingest-git <repo> [--since] [--until] [--author] [--max-commits-per-file]
                             [--include] [--exclude] [--include-merges]
                             [--dry-run] [--force] [--embed]
gnosis-mcp crawl <url> [--sitemap] [--max-depth N] [--include] [--exclude] [--max-pages N]
                       [--dry-run] [--force] [--embed]
gnosis-mcp serve [--transport stdio|sse|streamable-http] [--host HOST] [--port PORT]
                 [--ingest PATH] [--watch PATH] [--rest]
gnosis-mcp search <query> [-n LIMIT] [-c CAT] [--embed]    Search docs
gnosis-mcp stats                                           Document, chunk, and embedding counts
gnosis-mcp check                                           Verify DB connection + extensions
gnosis-mcp embed [--provider P] [--model M] [--batch-size N] [--dry-run]
gnosis-mcp init-db [--dry-run]                             Create tables + indexes
gnosis-mcp export [-f json|markdown] [-c CAT]              Export documents
gnosis-mcp diff <path>                                     Preview changes on re-ingest
gnosis-mcp prune <path> [--dry-run] [--include-crawled]    Delete chunks for missing files
gnosis-mcp cleanup [--days N]                              Purge old access log entries
gnosis-mcp eval [--json]                                   Retrieval quality harness (Hit@5, MRR, P@5)
gnosis-mcp fix-link-types                                  Migrate pre-0.10 git-history links
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
├── server.py          FastMCP server — 9 tools, 3 resources, auto-embed queries
├── ingest.py          File scanner + converters — multi-format, smart chunking
├── crawl.py           Web crawler — sitemap/BFS, robots.txt, ETag caching
├── parsers/           Non-file ingest sources (git history, future: schemas)
│   └── git_history.py Git log → markdown documents per file
├── watch.py           File watcher — mtime polling, auto-re-ingest
├── schema.py          PostgreSQL DDL — tables, indexes, search functions
├── embed.py           Embedding providers — OpenAI, Ollama, custom, local ONNX
├── local_embed.py     Local ONNX embedding engine — HuggingFace model download
└── cli.py             CLI — serve, ingest, crawl, search, embed, stats, check, cleanup
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
pytest                    # 632 tests, no database needed
ruff check src/ tests/
```

All tests run without a database. Keep it that way.

Good first contributions: new embedding providers, export formats, ingestion for new file types (via optional extras). Open an issue first for larger changes.

## Sponsors

If Gnosis MCP saves you time, consider [sponsoring the project](https://github.com/sponsors/nicholasglazer).

## License

[MIT](LICENSE)
