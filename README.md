<!-- mcp-name: io.github.nicholasglazer/gnosis -->
<div align="center">

<h1>Gnosis MCP</h1>

<p><strong>Stop pasting files into context. Your AI agent searches your local docs instead.<br>5–10× fewer tokens per lookup. 92 % Hit@5 on real dev docs. Zero cloud dependencies.</strong></p>

<p>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/v/gnosis-mcp?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/dm/gnosis-mcp?color=green" alt="Downloads"></a>
  <a href="https://pypi.org/project/gnosis-mcp/"><img src="https://img.shields.io/pypi/pyversions/gnosis-mcp" alt="Python"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/nicholasglazer/gnosis-mcp/actions"><img src="https://github.com/nicholasglazer/gnosis-mcp/actions/workflows/publish.yml/badge.svg" alt="CI"></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#documentation">Documentation</a> &middot;
  <a href="#tools">Tools</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-full.txt">Full Reference</a>
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
- **Cross-encoder reranking** — optional `[reranking]` extra with a 22M-param ONNX model. Off by default. **[Test on your own corpus before enabling](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/bench-experiments-2026-04-18.md)** — the bundled MS-MARCO reranker hurts dev-doc retrieval in our measurements.
- **Git history** — ingest commit messages as searchable context (`ingest-git`)
- **Web crawl** — ingest documentation from any website via sitemap or link crawl
- **Multi-format** — `.md` `.txt` `.ipynb` `.toml` `.csv` `.json` + optional `.rst` `.pdf`
- **Auto-linking** — `relates_to` frontmatter creates a navigable document graph
- **Watch mode** — auto-re-ingest on file changes
- **Prune stale docs** — `gnosis-mcp ingest --prune` removes chunks whose source file was deleted. `--wipe` for a full reset before re-ingest.
- **Built-in eval harness** — `gnosis-mcp eval` prints Hit@K / MRR / Precision@K in one command, against a bundled fixed fixture set
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

**Reproducible.** `gnosis-mcp eval` runs a bundled retrieval-quality harness locally in one second — but it ingests nine hardcoded sample documents into a temporary database and answers ten bundled queries, so it returns the same numbers for every corpus and is a smoke test, not a measurement of your docs. To score your own corpus, run `python tests/bench/bench_real_corpus.py --corpus <docs-root> --golden <golden.jsonl>` (the numbers above come from `tests/bench/golden-knowledge.jsonl`). `tests/bench/*.py` reproduce every number. Methodology: [`docs/benchmarks.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/benchmarks.md).

**Rerankers stay off by default.** The bundled MS-MARCO cross-encoder drops nDCG@10 by 27 points on dev-docs and adds 400× latency; BGE-reranker-v2-m3 drops it 31 points at 2400×. Test on your corpus before enabling — full write-up: [bench-experiments-2026-04-18](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/bench-experiments-2026-04-18.md).

## Quick Start

```bash
pip install gnosis-mcp           # or: uv tool install gnosis-mcp
gnosis-mcp ingest ./docs/        # loads docs into SQLite (auto-created)
gnosis-mcp serve                 # starts MCP server
```

That's it. Your AI agent can now search your docs.

**Connect your client** — see [`llms-install.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md) for copy-paste JSON snippets for Claude Code, Claude Desktop, Cursor, Zed, opencode, Windsurf, VS Code, JetBrains, Cline, and any other MCP client.

**Re-organized your docs?** `gnosis-mcp ingest ./docs --prune` re-ingests and removes any DB chunk whose source file no longer exists. `--wipe` resets the entire index first. Or run `gnosis-mcp prune ./docs --dry-run` to preview what would be deleted. Pruning only touches documents this root is responsible for: crawled URLs and generated documents (git history) are left alone unless `--include-crawled` / `--include-generated` says otherwise.

**Want semantic search?** Add local embeddings — no API key needed:

```bash
pip install gnosis-mcp[embeddings]
gnosis-mcp ingest ./docs/ --embed   # ingest + embed in one step
gnosis-mcp serve                    # hybrid search auto-activated
```

Test it before connecting to an editor:

```bash
gnosis-mcp check                                # FTS5 + schema + row counts; non-zero exit = stop
gnosis-mcp search "getting started"             # keyword search
gnosis-mcp search "how does auth work" --embed  # hybrid semantic+keyword
gnosis-mcp stats                                # see what was indexed
```

`gnosis-mcp check` is the gate: it exits `0` only when the backend started and the schema the
server needs is present, and it names whatever is missing before exiting `1`. Keyword search needs
SQLite **FTS5**, which is compiled into your Python's SQLite rather than guaranteed by it — `check`
reports it as `FTS5: ready`. Anything else: [`docs/troubleshooting.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/troubleshooting.md).

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

Or use the committed [`docker-compose.yaml`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docker-compose.yaml):

```bash
docker compose up -d
docker compose exec gnosis gnosis-mcp ingest /docs --embed
```

Images tagged `:latest`, `:<version>`, `:<version-minor>`, `:main`, `:sha-<sha>`. Production
recipes — systemd, reverse proxy, security checklist, upgrades — are in
[`docs/deployment.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/deployment.md).

</details>

<details>
<summary>Try without installing (uvx)</summary>

```bash
uvx gnosis-mcp ingest ./docs/
uvx gnosis-mcp serve
```

</details>

## Documentation

Canonical index — every topic is one hop away: **[`docs/overview.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/overview.md)**.

The handful most readers need:

- [**Install & client setup**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md) — every editor's copy-paste config, Windows paths, write mode, embeddings
- [**CLI**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/cli.md) — every subcommand and flag
- [**Configuration**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/config.md) — all `GNOSIS_MCP_*` env vars
- [**MCP tools & resources**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/tools.md) — what your agent can call, and what each returns
- [**Deployment**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/deployment.md) — Docker, systemd, reverse proxy, security checklist
- [**Troubleshooting**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/troubleshooting.md) — first-run failures and how to recover
- [**Benchmarks**](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/benchmarks.md) — reproducible retrieval and latency numbers

Also in `docs/`: [REST API](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/rest-api.md) · [embeddings service](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/embeddings-service.md) · [how we measure search](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/how-we-measure-search.md) · [reranker experiments](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/bench-experiments-2026-04-18.md) · [releasing](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/releasing.md).

## Tools

Gnosis MCP exposes nine tools and three resources over [MCP](https://modelcontextprotocol.io/). Your AI agent calls these automatically when it needs information from your docs:

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

The six read tools are always advertised. The three write tools require `GNOSIS_MCP_WRITABLE=true` — without it they are withdrawn from `tools/list` entirely, so a read-only client is never handed a tool it cannot call.

| Resource URI | Returns |
|-----|---------|
| `gnosis://docs` | All documents — path, title, category, chunk count |
| `gnosis://docs/{path}` | Full document content |
| `gnosis://categories` | Categories with document counts |

With embeddings configured, `search_docs` fuses keyword and semantic results with Reciprocal Rank Fusion and returns a `highlight` field carrying the matched terms in `<mark>` tags — that is what keeps a lookup at a few hundred tokens instead of a full file. `get_context` is the session-start tool: it ranks documents by how often they are actually retrieved, unless `GNOSIS_MCP_ACCESS_LOG=false` turns tracking off.

Full reference — every parameter, return shape, error, and the graph relation types (`related`, `content_link`, `git_co_change`, `git_ref`, plus the typed frontmatter edges): **[`docs/tools.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/tools.md)**.

## Configuration

Nothing required for SQLite — zero config works. Override via `GNOSIS_MCP_*` env vars. The four most-asked:

| Variable | Default | Description |
|----------|---------|-------------|
| `GNOSIS_MCP_DATABASE_URL` | SQLite auto | PostgreSQL URL (backend auto-detects) or SQLite file path |
| `GNOSIS_MCP_WRITABLE` | `false` | Enable `upsert_doc` / `delete_doc` / `update_metadata` |
| `GNOSIS_MCP_EMBED_PROVIDER` | unset | `local` turns on hybrid search (needs `[embeddings]` extra); or `openai` / `ollama` / `custom` |
| `GNOSIS_MCP_API_KEY` | unset | Optional Bearer auth for every REST endpoint except `/health` |

The remaining 45 — chunking, search limits, RRF, reranking, crawl, webhooks, column overrides, logging — are documented in **[`docs/config.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/config.md)**.

Backend selection is automatic: set `GNOSIS_MCP_DATABASE_URL` to a `postgresql://` URL and it uses PostgreSQL; leave it unset and it uses SQLite at `~/.local/share/gnosis-mcp/docs.db`. Override with `GNOSIS_MCP_BACKEND=sqlite|postgres`. PostgreSQL setup — `gnosis-mcp[postgres]`, `gnosis-mcp init-db`, `CREATE EXTENSION IF NOT EXISTS vector`, then `gnosis-mcp embed` — is in [`docs/overview.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/overview.md).

### Embeddings

Semantic search is the one optional add-on most setups want. Local ONNX is the recommended path: zero config, no API key, ~23 MB quantized model ([MongoDB/mdbr-leaf-ir](https://huggingface.co/MongoDB/mdbr-leaf-ir), Apache 2.0) auto-downloaded on first run.

```bash
pip install gnosis-mcp[embeddings]
gnosis-mcp ingest ./docs/ --embed   # ingest + embed in one step
gnosis-mcp embed                    # or backfill existing chunks separately
```

Remote providers work the same way via `gnosis-mcp embed --provider openai` (needs `GNOSIS_MCP_EMBED_API_KEY`) or `--provider ollama`. Model choices, dimensions, the OpenAI-compatible `POST /v1/embed` service, and pre-computed vectors for your own pipeline: [`docs/embeddings-service.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/embeddings-service.md) · [`docs/config.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/config.md#embeddings).

## Available On

[MCP Registry](https://registry.modelcontextprotocol.io) (feeds VS Code MCP gallery and GitHub Copilot) · [PyPI](https://pypi.org/project/gnosis-mcp/) · [mcp.so](https://mcp.so) · [Glama](https://glama.ai) · [cursor.directory](https://cursor.directory)

## AI-Friendly Docs

| File | Purpose |
|------|---------|
| [`llms.txt`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms.txt) | Quick overview — what it does, tools, config |
| [`llms-full.txt`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-full.txt) | Complete reference in one file |
| [`llms-install.md`](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md) | Step-by-step installation guide |

## Development

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 782 tests, no database needed
ruff check src/ tests/
```

All tests run without a database. Keep it that way.

Good first contributions: new embedding providers, export formats, ingestion for new file types (via optional extras). Open an issue first for larger changes.

## Sponsors

If Gnosis MCP saves you time, consider [sponsoring the project](https://github.com/sponsors/nicholasglazer).

## License

[MIT](https://github.com/nicholasglazer/gnosis-mcp/blob/main/LICENSE)

## Learn more

- [Documentation index](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/overview.md) — the canonical map of every docs page
- [Installation guide](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md) — copy-paste setup for every MCP client
- [Published docs](https://gnosismcp.com/doc/) — the same docs, rendered for browsing
- [PyPI](https://pypi.org/project/gnosis-mcp/) — releases, version history, install
- [Why this exists](https://teru.sh/blog/gnosis-mcp-docs-in-60ms/) — the write-up behind gnosis-mcp
