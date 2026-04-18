---
title: CLI Reference
category: docs
audience: all
relates_to:
  - README.md
  - docs/tools.md
  - docs/config.md
  - docs/rest-api.md
---

# CLI Reference

Every subcommand of `gnosis-mcp`. All commands honour `GNOSIS_MCP_*` env
vars (see [config.md](config.md)) — flags override env.

## Quick map

| Command | Purpose |
| ------- | ------- |
| [`serve`](#serve) | Start the MCP server (stdio / HTTP). |
| [`init-db`](#init-db) | Create tables, indexes, triggers. |
| [`ingest`](#ingest) | Ingest local files (md / txt / ipynb / toml / csv / json / rst / pdf). |
| [`prune`](#prune) | Delete chunks whose source file is gone. |
| [`ingest-git`](#ingest-git) | Index a git repo's commit history. |
| [`crawl`](#crawl) | Crawl a documentation website and ingest pages. |
| [`search`](#search) | Run a search from the command line (sanity check). |
| [`embed`](#embed) | Backfill embeddings for NULL rows. |
| [`stats`](#stats) | Print doc / chunk / embedding / access counts. |
| [`export`](#export) | Dump documents as JSON or markdown. |
| [`diff`](#diff) | Dry-run re-ingest: show what would change. |
| [`check`](#check) | Verify DB connection, schema, and extensions. |
| [`cleanup`](#cleanup) | Purge old access-log rows. |
| [`fix-link-types`](#fix-link-types) | One-off migration for pre-0.10 git-history links. |
| [`eval`](#eval) | Retrieval-quality harness (Hit@K, MRR, Precision@K). |

---

## `serve`

Start the MCP server.

```bash
gnosis-mcp serve [--transport {stdio,streamable-http,sse}]
                 [--host HOST] [--port PORT]
                 [--ingest PATH] [--watch PATH]
                 [--rest]
```

| Flag | Description |
| ---- | ----------- |
| `--transport` | `stdio` (default, for editor clients) or `streamable-http` (serve over HTTP). |
| `--host` | HTTP bind (default `127.0.0.1`; env `GNOSIS_MCP_HOST`). |
| `--port` | HTTP port (default `8000`; env `GNOSIS_MCP_PORT`). |
| `--ingest` | Ingest this path before starting. |
| `--watch` | Watch path for changes, auto-re-ingest (implies `--ingest`). Uses mtime polling with debounce. |
| `--rest` | Enable the REST API on the same HTTP port. See [rest-api.md](rest-api.md). |

**Examples**

```bash
# Default: stdio, SQLite at ~/.local/share/gnosis-mcp/docs.db
gnosis-mcp serve

# Network-accessible MCP + REST with local embeddings
GNOSIS_MCP_EMBED_PROVIDER=local \
gnosis-mcp serve --transport streamable-http --host 0.0.0.0 --rest

# Live-updating from a watched folder
gnosis-mcp serve --watch ./knowledge
```

---

## `init-db`

Create the tables, FTS5 / tsvector indexes, triggers, and (on Postgres) the
HNSW vector index. Idempotent.

```bash
gnosis-mcp init-db [--dry-run]
```

`--dry-run` prints the SQL without running it.

---

## `ingest`

Ingest local files. Walks directories, respects file type, chunks by
heading depth, skips unchanged files via content hash.

```bash
gnosis-mcp ingest PATH
    [--dry-run] [--force] [--embed]
    [--prune] [--wipe] [--include-crawled]
```

| Flag | Description |
| ---- | ----------- |
| `PATH` | File or directory to ingest. |
| `--dry-run` | Show what would happen, write nothing. |
| `--force` | Re-ingest every file even if content hash matches. |
| `--embed` | Generate embeddings for new/changed chunks (requires an embed provider). |
| `--prune` | After ingest, delete chunks whose source file is gone. |
| `--wipe` | Delete every document first (full reset — the nuclear option). |
| `--include-crawled` | When pruning, also consider crawled URLs. Default is to leave them alone. |

**Supported formats**

| Extension | Enabled by |
| --------- | ---------- |
| `.md` | core |
| `.txt` | core |
| `.ipynb` | core (code + markdown cells joined) |
| `.toml` | core |
| `.csv` | core |
| `.json` | core |
| `.rst` | `pip install gnosis-mcp[rst]` |
| `.pdf` | `pip install gnosis-mcp[pdf]` |

**Frontmatter**

Ingest extracts YAML frontmatter:
- `title:` — override first-H1 heuristic
- `category:`, `audience:`, `tags:` — metadata
- `relates_to:` — inline or list form, emits `related` edges
- `relations:` — typed-edge block (`type: prerequisite` etc.)

Body links (`[text](path.md)`, `[[wikilinks]]`) become `content_link` edges.

---

## `prune`

Delete chunks whose source file no longer exists on disk.

```bash
gnosis-mcp prune PATH [--dry-run] [--include-crawled]
```

Safer than `--wipe`: only touches chunks whose `file_path` was a local file
under `PATH` and that file is gone. Crawled URLs are skipped unless you
pass `--include-crawled`.

---

## `ingest-git`

Ingest commit history as searchable documents. One markdown doc per file,
listing the latest commits that touched it. Cross-file co-edit links get
`git_co_change`; source-file mentions get `git_ref`.

```bash
gnosis-mcp ingest-git REPO
    [--since WHEN] [--until WHEN] [--author SUB]
    [--max-commits-per-file N]
    [--include GLOB] [--exclude GLOB]
    [--include-merges]
    [--dry-run] [--force] [--embed]
```

| Flag | Description |
| ---- | ----------- |
| `--since`, `--until` | Date windows. `6m` / `2w` / `2025-01-01` all work. |
| `--author` | Filter by author name or email substring. |
| `--max-commits-per-file` | Default `10` (most recent). |
| `--include`, `--exclude` | Glob filters on the file set. |
| `--include-merges` | Default off (merge commits excluded). |

---

## `crawl`

Crawl a documentation website and ingest pages as markdown. Deferred
imports — requires `pip install gnosis-mcp[web]`.

```bash
gnosis-mcp crawl URL
    [--sitemap] [--max-depth N]
    [--include GLOB] [--exclude GLOB]
    [--max-pages N]
    [--dry-run] [--force] [--embed]
```

| Flag | Description |
| ---- | ----------- |
| `--sitemap` | Discover URLs via `sitemap.xml`. Best for large doc sites. |
| `--max-depth` | BFS link-crawl depth when `--sitemap` is off (default `1`). |
| `--include` / `--exclude` | Path glob filters. |
| `--max-pages` | Safety cap (default `5000`). |
| `--force` | Ignore the ETag / Last-Modified / hash cache. |

**Caching.** A JSON sidecar at `~/.local/share/gnosis-mcp/crawl-cache.json`
stores ETag and hash metadata so subsequent crawls can skip unchanged pages
via conditional requests.

**robots.txt.** Respected. Same-host redirect on `robots.txt` is treated as
`disallow` to block redirect-based spoofing.

---

## `search`

Quick retrieval sanity check from the shell.

```bash
gnosis-mcp search "your query" [-n 10] [-c guides] [--embed]
```

| Flag | Description |
| ---- | ----------- |
| `-n`, `--limit` | Max results (default `5`). |
| `-c`, `--category` | Filter by category. |
| `--embed` | Auto-embed the query for hybrid search (needs an embed provider). |

---

## `embed`

Backfill embeddings for chunks where `embedding IS NULL`.

```bash
gnosis-mcp embed
    [--provider {openai,ollama,custom,local}]
    [--model NAME] [--batch-size N] [--dry-run]
```

Flags override the `GNOSIS_MCP_EMBED_*` env vars.

---

## `stats`

Print a snapshot: doc count, chunk count, coverage of embeddings, top
categories, access-log size.

```bash
gnosis-mcp stats
```

---

## `export`

Dump documents for external pipelines.

```bash
gnosis-mcp export [-f {json,markdown}] [-c CATEGORY]
```

JSON output is a stream of `{file_path, title, category, content, ...}`
objects — friendly for piping into `jq`.

---

## `diff`

Dry-run re-ingest: show which files would be re-chunked and which would
skip (hash match).

```bash
gnosis-mcp diff PATH
```

---

## `check`

Verify that:
1. The database is reachable.
2. All required tables / extensions are present.
3. FTS5 (SQLite) or tsvector (Postgres) is functional.

Exit `0` on healthy, non-zero with a remediation hint otherwise. Good for
Docker `HEALTHCHECK` and CI smoke tests.

```bash
gnosis-mcp check
```

---

## `cleanup`

Purge old access-log rows.

```bash
gnosis-mcp cleanup [--days N]
```

Default keeps the last `90` days. `get_context`'s popularity signal still
works after trimming — recency weights recent accesses higher.

---

## `fix-link-types`

One-off migration. Pre-0.10 git-history docs used generic `relates_to`
edges; this command re-classifies them as `git_co_change` / `git_ref` so
`get_graph_stats()` can separate curated links from the noisier git-derived
ones. Safe to run multiple times.

```bash
gnosis-mcp fix-link-types
```

---

## `eval`

Retrieval-quality harness. Runs a small built-in query set against the
indexed corpus and reports Hit@5, MRR, Precision@5.

```bash
gnosis-mcp eval [--json]
```

`--json` emits the metrics only, suitable for piping into CI dashboards.
Use with `--force` re-ingest during benchmarks.

---

## Environment overrides

Every flag mentioned above has an env-var equivalent under `GNOSIS_MCP_*`
(see [config.md](config.md)). Env wins over interactive defaults; flags
win over env.

---

## See also

- [Configuration](config.md)
- [MCP tools](tools.md)
- [REST API](rest-api.md)
