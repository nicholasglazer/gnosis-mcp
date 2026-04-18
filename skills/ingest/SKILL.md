---
name: ingest
description: Populate the gnosis-mcp knowledge base — from local files, git history, or a crawled website. Handles the full matrix of flags (--force, --prune, --wipe, --embed, --include-crawled) in one place.
disable-model-invocation: true
---

# Ingest

One skill that covers every way to get content into gnosis-mcp. Routes
based on `$ARGUMENTS`:

- Path to a directory / file → local file ingest
- `git <repo>` → git-history ingest
- `crawl <url>` → web-crawl ingest
- `reingest` → full reset + re-ingest from the default path
- `prune <path>` → delete DB chunks whose source is gone

## Action: $ARGUMENTS

---

## `ingest <path>` — local files

Default entry point. Handles `.md`, `.txt`, `.ipynb`, `.toml`, `.csv`,
`.json` (+ `.rst` / `.pdf` if those extras are installed).

### First-time ingest

```bash
gnosis-mcp ingest ./docs --embed
```

- `--embed` runs the bundled ONNX embedder (requires `[embeddings]`
  extra). Without it you get keyword-only search — usually enough for
  dev-doc corpora (see bench-experiments), but `--embed` costs nothing
  on a first ingest and enables hybrid later if you want it.
- Incremental: every file's content hash is stored, so re-running only
  processes changed files. Use `--force` to re-ingest regardless.

### Chunk size

Default is **2000 characters** (~600 tokens) — peak of the Feb 2026
sweep on a real dev-docs corpus. Override per-ingest or globally:

```bash
# This invocation only
GNOSIS_MCP_CHUNK_SIZE=1500 gnosis-mcp ingest ./docs --embed

# Persistent (put in shell profile)
export GNOSIS_MCP_CHUNK_SIZE=3000   # long-form blogs / ADRs
```

If you're unsure, run `/gnosis:tune` to sweep sizes against your own
golden queries.

### Reorganized your knowledge folder

Files moved, deleted, renamed. Pick one:

```bash
# Safest: re-ingest + drop chunks for files that no longer exist
gnosis-mcp ingest ./docs --embed --prune

# Nuclear: drop everything first, then re-ingest
gnosis-mcp ingest ./docs --embed --wipe

# Preview what prune would delete
gnosis-mcp prune ./docs --dry-run
```

By default `--prune` leaves *crawled* URLs alone (since those don't
correspond to local files). Add `--include-crawled` if you want those
gone too.

---

## `ingest git <repo>` — git commit history

Indexes each file's commit history as a searchable markdown document.
Lets your agent answer "why does this code exist" queries.

```bash
gnosis-mcp ingest-git /path/to/repo --since 6m --embed
```

Common flags:

| Flag | Effect |
|---|---|
| `--since 6m` / `--since 2025-01-01` | Window of commits to include |
| `--until 2026-03-01` | Upper bound |
| `--author "alice@"` | Filter by author name or email substring |
| `--max-commits-per-file 20` | Default 10, most-recent wins |
| `--include "src/**"` | Glob filter on touched files |
| `--exclude "*.lock,package.json"` | Skip noisy files |
| `--include-merges` | Default excludes merge commits |

Each indexed doc's `file_path` is `git-history/<original-path>.md`.
Cross-file co-edits generate `git_co_change` edges; source-file
references get `git_ref`. Query them via
`mcp__gnosis__search_git_history` (or filter `mcp__gnosis__get_related`
by `relation_type=git_co_change`).

Re-run `ingest-git` whenever your history grows past the window you
already indexed.

---

## `ingest crawl <url>` — web crawl

Indexes a documentation website. Requires the `[web]` extra
(`pip install 'gnosis-mcp[web]'`).

```bash
# Preferred — discover URLs from sitemap.xml
gnosis-mcp crawl https://docs.stripe.com --sitemap --embed

# No sitemap? BFS link crawl, one hop deep
gnosis-mcp crawl https://docs.example.com --max-depth 1 --embed

# Subset only
gnosis-mcp crawl https://docs.example.com --sitemap \
  --include "/docs/api/**" --exclude "*.pdf"

# Preview, don't fetch
gnosis-mcp crawl https://docs.example.com --dry-run
```

Other flags:

| Flag | Effect |
|---|---|
| `--max-pages 5000` | Safety cap |
| `--force` | Ignore the ETag / Last-Modified / hash cache |

Behaviour:

- Respects `robots.txt`. A same-host redirect on `/robots.txt` is
  treated as disallow (prevents spoofing).
- Caches ETag + Last-Modified + content hash at
  `~/.local/share/gnosis-mcp/crawl-cache.json` — subsequent crawls
  issue conditional GETs and skip unchanged pages.
- Extracts markdown via trafilatura with a 30 s per-page timeout
  (`GNOSIS_MCP_CRAWL_EXTRACT_TIMEOUT_S`).

**Vendor docs strategy**: crawl them once, commit the indexed SQLite
to version control, and you have offline, searchable vendor docs
alongside your private docs. No Context7 subscription required.

---

## `ingest reingest` — full reset

Drop everything, reinitialise, reindex. Use when:

- You changed embedder (`GNOSIS_MCP_EMBED_MODEL` or `_EMBED_DIM`) —
  old vectors are now incompatible
- You want to force a clean baseline before a benchmark
- Schema drifted (rare, but `init-db` is idempotent so rerunning is safe)

```bash
gnosis-mcp init-db                        # ensure schema is current
gnosis-mcp ingest ./docs --embed --wipe   # delete everything + reingest
gnosis-mcp stats                           # confirm
```

---

## `ingest prune <path>` — dead-chunk cleanup

Standalone prune, independent of re-ingest.

```bash
# What would go
gnosis-mcp prune ./docs --dry-run

# Delete chunks for files no longer on disk under ./docs
gnosis-mcp prune ./docs

# Also drop crawled URLs (normally spared)
gnosis-mcp prune ./docs --include-crawled
```

Safer than `--wipe` because it only deletes rows whose original
`file_path` resolved as a local file under the given root AND is now
missing. Crawled URLs, git-history docs (`git-history/*`), and any
path outside the root are untouched unless you explicitly opt in.

---

## Watch mode (server-side auto-reingest)

Skip the manual re-run loop — the server can watch a folder and
re-ingest on file changes.

```bash
gnosis-mcp serve --watch ./docs --transport streamable-http --rest
```

Mtime polling + debounce. Works on every OS, no fsnotify dependency.
Ideal for docs-as-code repos where you push a doc and want it searchable
by your editor within a few seconds.

---

## Verify afterwards

Always run `gnosis-mcp stats` (or `/gnosis:status stats`) after a big
ingest to confirm:

- Doc count matches expectations
- Chunk count is sensible (~1-5 chunks per doc for ~2000-char chunk size)
- Embeddings coverage is 100 % if you used `--embed`
- No vec0 table errors

```
$ gnosis-mcp stats
Documents: 558
Chunks:    1,742
Embeddings: 1,742 / 1,742 (100.0 %)
Last access log entry: 2026-04-18 07:12 UTC
Backend: sqlite
```

---

## See also

- `/gnosis:tune` — chunk-size sweep on your own corpus
- `/gnosis:status` — connectivity + DB health
- `/gnosis:search` — query the index you just populated
- [config reference](https://gnosismcp.com/doc/docs/config) for every
  `GNOSIS_MCP_*` env var
- [CLI reference](https://gnosismcp.com/doc/docs/cli) for every flag
