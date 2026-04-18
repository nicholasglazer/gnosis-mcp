---
title: Documentation
category: docs
audience: all
relates_to:
  - README.md
  - docs/tools.md
  - docs/config.md
  - docs/cli.md
  - docs/rest-api.md
  - docs/benchmarks.md
---

# Documentation

**gnosis-mcp** is a self-hosted MCP server that indexes your docs, git
history, and crawled sites into a searchable knowledge base for AI agents.
Zero config. SQLite default. Hybrid FTS5 + vector with optional
cross-encoder reranking. Python 3.11+, MIT.

This is the canonical documentation. Every topic links in one hop.

---

## Install

```bash
pip install gnosis-mcp            # core
pip install gnosis-mcp[embeddings] # local ONNX vectors
pip install gnosis-mcp[reranking]  # cross-encoder rerank
pip install gnosis-mcp[postgres]   # production backend
pip install gnosis-mcp[web]        # web crawling
pip install gnosis-mcp[rst,pdf]    # extra input formats
```

`pip install "gnosis-mcp[embeddings,postgres,web]"` for the full stack.

---

## 60-second quickstart

```bash
# 1. index your docs
gnosis-mcp ingest ./knowledge

# 2. serve (MCP stdio by default — for Claude Code, Cursor, Windsurf, …)
gnosis-mcp serve

# or expose on HTTP with a REST mirror
gnosis-mcp serve --transport streamable-http --rest
```

Point your editor at it. See [`llms-install.md`](../llms-install.md) for
copy-paste snippets for every popular client.

---

## Reference

Start here:

- [**MCP Tools**](tools.md) — the 9 tools + 3 resources. This is the API
  your LLM sees.
- [**CLI**](cli.md) — every subcommand (`serve`, `ingest`, `crawl`,
  `ingest-git`, `embed`, `search`, `stats`, `export`, `diff`, `check`,
  `cleanup`, `prune`, `fix-link-types`, `eval`, `init-db`).
- [**Configuration**](config.md) — every `GNOSIS_MCP_*` environment
  variable, grouped by what it controls.
- [**REST API**](rest-api.md) — optional HTTP/JSON mirror on the same port.
- [**Deployment**](deployment.md) — Docker, systemd, reverse proxy,
  Cloudflare Tunnel, security checklist, upgrades.
- [**Troubleshooting**](troubleshooting.md) — common failures and how to
  recover.
- [**Benchmarks**](benchmarks.md) — published QPS / latency numbers with
  methodology you can reproduce.

---

## Concepts in one page

### Backends

gnosis-mcp has two first-class backends, both maintained in-tree:

| | SQLite | PostgreSQL |
| --- | --- | --- |
| Install | core | `[postgres]` extra |
| Good for | dev, laptop-scale ≤ 100 k chunks | production, concurrent writers, multi-GB corpora |
| Keyword search | FTS5 + BM25, porter tokenizer | tsvector + GIN |
| Vector search | `sqlite-vec` + HNSW | `pgvector` + HNSW |
| Hybrid | Reciprocal Rank Fusion | Reciprocal Rank Fusion |

Both implement the same `DocBackend` Protocol. Tool API is identical; the
SQL underneath differs.

### Ingestion

- Files (`ingest`) — `.md`, `.txt`, `.ipynb`, `.toml`, `.csv`, `.json` out
  of the box; `.rst` + `.pdf` via extras.
- Git history (`ingest-git`) — one doc per source file, listing the
  commits that touched it. Cross-file co-edit links become
  `git_co_change` edges.
- Web crawl (`crawl`) — sitemap or BFS, robots-aware, HTML → markdown via
  trafilatura.
- Watch mode (`serve --watch`) — mtime-poll + debounce, auto-re-embeds
  changed chunks.

All ingesters hash content — unchanged files are skipped on re-run.

### Search

- **Keyword** — FTS5 on SQLite, tsvector on Postgres. BM25-ranked.
- **Vector** — `sqlite-vec` (SQLite) or `pgvector` HNSW (Postgres). Cosine
  similarity.
- **Hybrid** — both fused with Reciprocal Rank Fusion
  (`score = Σ 1 / (k + rank_i)`; tune `k` via `GNOSIS_MCP_RRF_K`). RRF
  handles incompatible score scales correctly; linear-weighting does not.
- **Rerank** — optional ONNX cross-encoder (22 M params) that re-scores
  the top candidates. Off by default. ~20 ms added latency.

### Knowledge graph

Every document gets edges:

- `related` from frontmatter `relates_to:`
- Typed edges from the `relations:` frontmatter block (17 types —
  `prerequisite`, `depends_on`, `summarizes`, `extends`, `replaces`,
  `audited_by`, `implements`, `tests`, `example_of`, `references`, and
  inverses).
- `content_link` from markdown `[text](file.md)` and `[[wikilinks]]`.
- `git_co_change`, `git_ref` from `ingest-git`.

`get_related(path, depth)` walks the graph up to depth 3. `get_graph_stats`
reports orphans, hubs, and edge-type distribution.

### Write tools

Off by default. Set `GNOSIS_MCP_WRITABLE=true` to unlock `upsert_doc`,
`delete_doc`, `update_metadata`. Write tools fire a fire-and-forget
webhook (SSRF-guarded) so downstream caches can invalidate.

---

## Security-first defaults

- Write tools gated (`GNOSIS_MCP_WRITABLE=false` by default).
- Bearer auth comparison is timing-safe.
- HuggingFace model downloads enforced HTTPS + SHA-256 checksums.
- Webhook targets refuse private / loopback / link-local / multicast IPs
  unless explicitly allowed.
- `robots.txt` cross-host redirects treated as disallow.
- Content size caps on `upsert_doc`; query length caps on `search_docs`.
- Every SQL identifier validated at config-time against
  `^[a-zA-Z_][a-zA-Z0-9_]*$`.

---

## What next

- Pick a backend: [SQLite or Postgres?](config.md#core) — the default is
  fine until you need concurrent writers.
- Pick an embedding provider: [local ONNX, or remote?](config.md#embeddings) —
  local is private and free.
- Decide whether to enable reranking: see
  [rerank flag](config.md#reranking). Off by default; turn on if your
  recall-at-top-k matters.
- Wire your editor: [`llms-install.md`](../llms-install.md).

For anything not covered: open an issue or read the source — it is ~4 k
LOC across 10 modules, fully type-hinted.
