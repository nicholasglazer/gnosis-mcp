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

| Command                             | Purpose                                                                |
| ----------------------------------- | ---------------------------------------------------------------------- |
| [`serve`](#serve)                   | Start the MCP server (stdio / HTTP).                                   |
| [`init-db`](#init-db)               | Create tables, indexes, triggers.                                      |
| [`ingest`](#ingest)                 | Ingest local files (md / txt / ipynb / toml / csv / json / rst / pdf). |
| [`prune`](#prune)                   | Delete chunks whose source file is gone.                               |
| [`ingest-git`](#ingest-git)         | Index a git repo's commit history.                                     |
| [`crawl`](#crawl)                   | Crawl a documentation website and ingest pages.                        |
| [`search`](#search)                 | Run a search from the command line (sanity check).                     |
| [`embed`](#embed)                   | Backfill embeddings for NULL rows.                                     |
| [`stats`](#stats)                   | Print doc / chunk / embedding / access counts.                         |
| [`export`](#export)                 | Dump documents as JSON, markdown, or CSV.                              |
| [`diff`](#diff)                     | Dry-run re-ingest: show what would change.                             |
| [`check`](#check)                   | Verify DB connection, schema, and extensions.                          |
| [`setup`](#setup)                   | Wire the server into the MCP clients on this machine.                  |
| [`doctor`](#doctor)                 | Check the DB, the client wiring, and whether anything calls it.        |
| [`cleanup`](#cleanup)               | Purge old access-log rows.                                             |
| [`fix-link-types`](#fix-link-types) | One-off migration for pre-0.10 git-history links.                      |
| [`eval`](#eval)                     | Retrieval-quality harness (Hit@K, MRR, Precision@K).                   |
| [`savings`](#savings)               | Token-savings ledger from the access log.                              |
| [`usage`](#usage)                   | What was asked, what was served, and what was missed.                  |

---

## `serve`

Start the MCP server.

```bash
gnosis-mcp serve [--transport {stdio,streamable-http,sse}]
                 [--host HOST] [--port PORT]
                 [--ingest PATH] [--watch PATH]
                 [--search-limit-max N] [--content-preview-chars N]
                 [--rest]
```

| Flag                      | Description                                                                                            |
| ------------------------- | ------------------------------------------------------------------------------------------------------ |
| `--transport`             | `stdio` (default, for editor clients) or `streamable-http` (serve over HTTP).                          |
| `--host`                  | HTTP bind (default `127.0.0.1`; env `GNOSIS_MCP_HOST`).                                                |
| `--port`                  | HTTP port (default `8000`; env `GNOSIS_MCP_PORT`).                                                     |
| `--ingest`                | Ingest this path before starting.                                                                      |
| `--watch`                 | Watch path for changes, auto-re-ingest (implies `--ingest`). Uses mtime polling with debounce.         |
| `--search-limit-max`      | Cap on the result `limit` an MCP client may request (default `20`; env `GNOSIS_MCP_SEARCH_LIMIT_MAX`). |
| `--content-preview-chars` | Snippet length, in characters, in tool output (default `200`; env `GNOSIS_MCP_CONTENT_PREVIEW_CHARS`). |
| `--rest`                  | Enable the REST API on the same HTTP port. See [rest-api.md](rest-api.md).                             |

Both tuning flags are applied to the server's environment before startup, so the
MCP tools, the REST routes, and the watcher all read the same values.

Started against an empty database, `serve` runs one idempotent DDL pass to
create the schema — wiring a client up before the first `ingest` works instead
of failing every call with `no such table`.

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
    [--prune] [--wipe] [--include-crawled] [--include-generated]
```

| Flag                  | Description                                                                                                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PATH`                | File or directory to ingest.                                                                                                                                                  |
| `--dry-run`           | Show what would happen, write nothing.                                                                                                                                        |
| `--force`             | Re-ingest every file even if content hash matches.                                                                                                                            |
| `--embed`             | Generate embeddings for new/changed chunks (requires an embed provider).                                                                                                      |
| `--prune`             | After ingest, delete chunks whose source file is gone.                                                                                                                        |
| `--wipe`              | Delete every document first (full reset — the nuclear option).                                                                                                                |
| `--include-crawled`   | When pruning, also consider crawled URLs. Default is to leave them alone.                                                                                                     |
| `--include-generated` | When pruning, also consider generated documents such as git history. Default is to leave them alone — they have no file on disk, so pruning by root would always delete them. |

**Supported formats**

| Extension | Enabled by                          |
| --------- | ----------------------------------- |
| `.md`     | core                                |
| `.txt`    | core                                |
| `.ipynb`  | core (code + markdown cells joined) |
| `.toml`   | core                                |
| `.csv`    | core                                |
| `.json`   | core                                |
| `.rst`    | `pip install gnosis-mcp[rst]`       |
| `.pdf`    | `pip install gnosis-mcp[pdf]`       |

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
gnosis-mcp prune PATH [--dry-run] [--include-crawled] [--include-generated]
```

Safer than `--wipe`: only touches chunks whose `file_path` was a local file
under `PATH` and that file is gone. Crawled URLs are skipped unless you
pass `--include-crawled`. Generated documents (git history) are likewise kept unless
`--include-generated` is passed.

---

## `ingest-git`

Ingest commit history as searchable documents. One markdown doc per file,
listing the latest commits that touched it. Cross-file co-edit links get
`git_co_change`; source-file mentions get `git_ref`.

```bash
gnosis-mcp ingest-git REPO
    [--since WHEN] [--until WHEN] [--author SUB]
    [--max-commits N]
    [--include GLOB] [--exclude GLOB]
    [--merges]
    [--dry-run] [--force] [--embed]
```

| Flag                     | Description                                                  |
| ------------------------ | ------------------------------------------------------------ |
| `--since`, `--until`     | Date windows. `6m` / `2w` / `2025-01-01` all work.           |
| `--author`               | Filter by author name or email substring.                    |
| `--max-commits`          | Max commits per file, most recent first. Default `10`.       |
| `--include`, `--exclude` | Glob filters on the file set.                                |
| `--merges`               | Include merge commits (excluded by default). Takes no value. |

---

## `crawl`

Crawl a documentation website and ingest pages as markdown. Deferred
imports — requires `pip install gnosis-mcp[web]`.

```bash
gnosis-mcp crawl URL
    [--sitemap] [--depth N]
    [--include GLOB] [--exclude GLOB]
    [--max-urls N]
    [--dry-run] [--force] [--embed]
```

| Flag                      | Description                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------ |
| `--sitemap`               | Discover URLs via `sitemap.xml`. Best for large doc sites.                           |
| `--depth`                 | BFS link-crawl depth when `--sitemap` is off. Default `1`; ignored with `--sitemap`. |
| `--include` / `--exclude` | Path glob filters.                                                                   |
| `--max-urls`              | Maximum number of URLs to crawl. Default `5000`.                                     |
| `--force`                 | Ignore the ETag / Last-Modified / hash cache.                                        |

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

| Flag               | Description                                                       |
| ------------------ | ----------------------------------------------------------------- |
| `-n`, `--limit`    | Max results (default `5`).                                        |
| `-c`, `--category` | Filter by category.                                               |
| `--embed`          | Auto-embed the query for hybrid search (needs an embed provider). |

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
gnosis-mcp export [-f {json,markdown,csv}] [-c CATEGORY]
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

Exit `0` when the backend starts and the tables the server needs are present,
and `1` otherwise: an unreachable backend, a failed health probe, or a database
that was never initialized — a missing chunks table, FTS5 index, or links table
each count as uninitialized. The failure path names the missing pieces and
prints the `gnosis-mcp init-db` hint, so the command can gate a setup script,
an installer, a Docker `HEALTHCHECK`, or CI.

```bash
gnosis-mcp check
```

---

## `setup`

Wire the server into the MCP clients installed on this machine, using the command
path that is correct _here_.

```bash
gnosis-mcp setup [--write] [--client NAME]... [--no-cli]
                 [--dsh-profile NAME] [--list] [--json]
```

Prints a preview by default; nothing is modified without `--write`. With no
`--client`, every client detected on the machine is offered — detection is
deliberately shallow (an existing config, a real vendor directory, or the
vendor's CLI on `PATH`), because a false positive costs one line of output while
a false negative hides a client the user then has to name by hand.

Two properties make it safe to re-run, which is the whole point: each installed
block is wrapped in markers naming the command that regenerates it, so a repeat
run rewrites one region in place rather than appending a duplicate, and nothing
outside the markers is read, reordered, or reformatted.

Where a client ships its own `mcp add` command (`claude`, `codex`, `gemini`),
that command is used and the config file is left to the vendor. If it exists but
fails, `setup` reports the failure rather than writing a rival config — pass
`--no-cli` to edit files directly regardless.

`--json` emits the full report for an agent or installer to consume. Exit `1`
when a requested client could not be wired.

The DeepSeek Harness row is written into the profile **patch layer**, so every
session on every preset gets the tools, and the profile reloads it live. Because
a harness that never reads the server's MCP `instructions` field would mount
tools the agent has no reason to prefer, `setup` also writes a short rule into
`$DSH_HOME/AGENTS.md`. If that file already holds a hand-written gnosis row with
no markers, `setup` refuses and says which row to delete rather than creating a
duplicate id.

Related: [`setup` in llms-install.md](../llms-install.md#wire-the-client) lists every
client, its config path, and its instruction file.

---

## `doctor`

Answer "is it installed, _and is it actually being used?_" in one pass.

```bash
gnosis-mcp doctor [--days N] [--strict] [--no-verify] [--dsh-profile NAME] [--json]
```

A superset of `check`. It prints database health, then which clients are wired
and where, then the clients the access log says have really called this server.

Two failures survive a passing `check`, and both are silent — no error, no log
line, no results:

- **Wired to a path that no longer exists.** The client starts, registers no
  tools, and says nothing. `doctor` resolves the command it would write and says
  whether that file is present.
- **Wired but never called.** The config expresses intent; only the access log
  proves an agent chose to use it. `doctor` reads `search_access_log` grouped by
  client, so a shared database shows which client has been calling and when.

Exit `1` on an unhealthy database, an uninitialized schema, no wired client, or a
composition the harness rejects. "Wired but never called" is a warning, not a
failure — a machine that installed gnosis five minutes ago is in exactly that
state. `--strict` promotes it to exit `1` for a CI job that means to assert real
usage.

`--no-verify` skips `dsh --dump-config`, which composes every layer of the
DeepSeek Harness profile and refuses to print a tree it cannot load — the only
check that catches a row the loader rejects rather than one that is merely
malformed.

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

Retrieval-quality smoke test. Reports Hit@K, MRR, and Precision@K (`K = 5`).

```bash
gnosis-mcp eval [--json]
```

**Read this before trusting the numbers.** `eval` does _not_ query your
corpus. It builds a fixed fixture — the hardcoded `SAMPLE_DOCS` /
`SAMPLE_GIT_HISTORY_DOCS` lists plus `tests/eval/cases.json` — in a
temporary SQLite database, and ignores `GNOSIS_MCP_DATABASE_URL` entirely.
The same numbers come out whatever you have indexed, so treat `eval` as a
regression check on the harness and a worked example of the metric
definitions, not as a measurement of your docs.

It also needs the repository checkout: it imports the fixtures from
`tests/eval/`, so a plain `pip install` (no `tests/` directory) exits `1`
with an install-from-source hint.

`--json` emits the metrics only, suitable for piping into CI dashboards:

```json
{
  "cases": 10,
  "hit_rate_at_k": 1.0,
  "mrr": 1.0,
  "mean_precision_at_k": 0.75,
  "k": 5
}
```

**Measuring your own corpus.** Use the real-corpus benchmark, which ingests
an arbitrary docs tree and scores it against your own golden queries:

```bash
python tests/bench/bench_real_corpus.py \
    --corpus /path/to/docs \
    --golden tests/bench/golden-knowledge.jsonl
```

`--corpus` is the markdown root to ingest; `--golden` is a JSONL file of
`{"query": "...", "expected_paths": ["docs/x.md"]}` lines. `--modes`,
`--k`, `--rerank-n`, `--title-prepend`, and `--chunk-size` let you compare
configurations. Unlike `eval`, this one reports nDCG@10 as well.

---

## `savings`

```bash
gnosis-mcp savings [--days N] [--json]
```

What the access log says your agents saved by searching this corpus instead of
reading whole documents: tool calls, tokens returned, the baseline those same
queries would have cost as full reads, and the resulting ratio — broken down per
tool, over the last `--days` (default 30). `--json` emits the same numbers for
scripting.

The ledger is written by `search_docs` (its top three hits) and `get_doc`. Turn it
off with `GNOSIS_MCP_ACCESS_LOG=false`, and purge it with
[`cleanup`](#cleanup).

---

## `usage`

```bash
gnosis-mcp usage [--days N] [--limit N] [--json]
```

Who consulted this corpus, what they were served, and what they asked that it
could not answer — over the last `--days` (default 30), ranking the top `--limit`
(default 10) documents and misses.

| Section        | What it tells you                                             |
| -------------- | ------------------------------------------------------------- |
| Calls / Misses | Volume, and the share of queries that matched nothing.        |
| Docs served    | Distinct documents returned in the window.                    |
| Never accessed | Indexed documents no query has ever surfaced, vs. the total.  |
| By tool        | `search_docs` vs `get_doc` — how agents actually read.        |
| By client      | Which MCP clients made the calls (see below).                 |
| Top documents  | Most-served paths — the corpus's real centre of gravity.      |
| Misses         | Queries logged with no hits: the index saying "nothing here". |

A **miss** is a `search_docs` call that matched nothing. It is recorded with an
empty `file_path` so it can never be mistaken for a served document; `usage`
ranks misses while [`get_context`](tools.md) and everything else that reads the
ledger as document usage skip them.

**By client** names the MCP client from the session's `initialize` handshake
(e.g. `claude-code/2.1.263`). Rows logged before the `client` column existed, or
by callers that send no client info, show up as unattributed — `usage` prints a
note rather than guessing.

The report reads the same access log as [`savings`](#savings): both need
`GNOSIS_MCP_ACCESS_LOG` on (the default), and windowed data is only as old as the
last [`cleanup`](#cleanup). `--json` emits the whole report for scripting.

---

## Environment overrides

Server-level settings also exist as `GNOSIS_MCP_*` environment variables (see
[config.md](config.md)); per-invocation switches such as `--dry-run`, `--json`,
`--force`, `--prune`, `--wipe`, `--sitemap`, `--merges` and `--include-crawled`
do not, because they answer a question about one run rather than configuring the
server. Where both exist, a flag wins over its environment variable.

---

## See also

- [Configuration](config.md)
- [MCP tools](tools.md)
- [REST API](rest-api.md)
