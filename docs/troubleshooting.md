---
title: Troubleshooting
category: docs
audience: all
relates_to:
  - README.md
  - docs/overview.md
  - docs/config.md
  - docs/cli.md
---

# Troubleshooting

Common failure modes, what they mean, and how to recover. Run
`gnosis-mcp check` first — it often names the problem in one line.

---

## Install

### `ERROR: Could not find a version that satisfies the requirement gnosis-mcp`
You're on Python < 3.11. `python --version` should report 3.11 or newer.

### `ImportError: sqlite3` or `cannot load sqlite-vec`
Your Python's `sqlite3` was built against an old SQLite (< 3.42) without
loadable extensions. Options:

1. Upgrade Python from python.org (ships a recent sqlite).
2. Use Postgres — `pip install gnosis-mcp[postgres]` then set
   `GNOSIS_MCP_DATABASE_URL=postgresql://…`.
3. On Linux distros, install `libsqlite3-dev` and rebuild Python.

### `ONNXRuntimeError: LoadLibrary failed`
ONNX Runtime couldn't load its native binary. Usually a mismatch between
`onnxruntime` and glibc on very old Linux. Options:

- `pip install onnxruntime==1.17.*` to pin a version with wider glibc
  support.
- Switch to a remote embed provider (set `GNOSIS_MCP_EMBED_PROVIDER=openai`
  or `ollama`) — avoids the native dep entirely.

---

## Database

### `gnosis-mcp check` reports *no such table: documentation_chunks*
You haven't initialised the database. Run `gnosis-mcp init-db` once.

### `gnosis-mcp check` reports *vec0 table not present* (SQLite)
You installed the core package without embeddings. This is fine if you're
only using keyword search. To enable hybrid:

```bash
pip install "gnosis-mcp[embeddings]"
gnosis-mcp init-db   # re-run; idempotent, creates vec0 table
```

### Postgres: *extension "vector" is not available*
pgvector isn't installed on your Postgres server.

- Docker: use `pgvector/pgvector:pg15` instead of `postgres:15`.
- Managed DB (Supabase, Neon, RDS): enable pgvector in the extensions
  panel (most managed providers support it).
- Bare-metal: install from source
  (`https://github.com/pgvector/pgvector`).

Then: `CREATE EXTENSION vector;` in your database, re-run `gnosis-mcp init-db`.

### *could not read a page from server* / pool saturation
`pool_max=3` (default) is small for heavy write loads. Raise it:

```bash
export GNOSIS_MCP_POOL_MAX=15
```

---

## MCP client integration

### Agent says "I can't find any docs on X"
Check in order:

1. `gnosis-mcp stats` — is the DB actually populated? If zero docs, you
   haven't ingested.
2. `gnosis-mcp search "X"` from the shell — does it work outside MCP? If
   yes, the MCP transport is the issue.
3. `gnosis-mcp check` — any errors?
4. Editor config — did you actually wire the server? See
   [`llms-install.md`](../llms-install.md).

### Stdio client hangs / "server not responding"
- Another `gnosis-mcp serve` process is holding the SQLite DB open in
  exclusive mode. `ps aux | grep gnosis-mcp` and kill stragglers.
- Your client is writing non-JSON to stdio. Check the client log — look
  for pre-handshake noise (warnings, print statements).

### "403 / auth" over HTTP
You set `GNOSIS_MCP_API_KEY` but the client isn't sending the
`Authorization: Bearer <key>` header, or the header value doesn't match
the env var. `curl -H "Authorization: Bearer $KEY"` from the shell to
confirm the key itself works.

---

## Ingestion

### Some files were skipped silently
Content hashing: if the file is unchanged since last ingest, it's skipped.
Use `--force` to re-ingest anyway, or `diff` to preview what would happen.

### "Chunk split inside a code fence" — wait, we promised that can't happen
It shouldn't. File an issue with a repro. In the meantime, move the
oversized code block to a sibling file and link to it.

### `.ipynb` ingested but the cells look weird
We join cell sources in document order, stripping outputs. Executed cells
with escape codes can produce noisy strings. Clear outputs first
(`jupyter nbconvert --clear-output ...`) or export the notebook to
markdown.

### `.pdf` ingest dies on a particular file
`pypdf` (our extractor) fails on malformed / scanned PDFs. Extract
manually with `pdftotext` and ingest the `.txt` result.

### Watch mode doesn't notice changes
We use mtime polling (works on every OS, no fsnotify dependency). Some
editors save-atomic (temp-file + rename), which changes the inode; mtime
still updates. If you're on a networked filesystem with mtime quirks,
touch the file manually to force detection.

### "No documents indexed. Run: gnosis-mcp ingest <path>"
Your search query returned zero results AND the `chunks` table is empty.
Exactly what the message says. Ingest something.

---

## Search

### Hybrid search isn't faster — in fact it's slower than keyword alone
Reranking is off by default but if you enabled it, expect +20 ms per
query. To confirm:

```bash
time gnosis-mcp search "your query"
GNOSIS_MCP_RERANK_ENABLED=false time gnosis-mcp search "your query"
```

### Semantic results don't look semantic
Check:

1. `gnosis-mcp stats` — are embeddings actually populated? It reports
   "N chunks with NULL embeddings".
2. You ingested with `--embed`, or you ran `gnosis-mcp embed` afterwards.
3. `GNOSIS_MCP_EMBED_PROVIDER` is set. Without it, queries don't get
   embedded and hybrid degrades to keyword.

### Tuning RRF
`GNOSIS_MCP_RRF_K` (default 60). Higher values flatten the rank curve and
let vector scores contribute more. If your queries are all keyword-ish
(code, identifiers), lower `k` (~30). If they're all natural language,
raise it (~120).

---

## Writes

### `upsert_doc` returns "write tools disabled"
`GNOSIS_MCP_WRITABLE` is unset or `false`. Set it to `true` in the env
of the server process (not the client).

### `upsert_doc` returns "content exceeds max_doc_bytes"
50 MB cap. Either split the doc or bump `GNOSIS_MCP_MAX_DOC_BYTES`. The
default exists so a client bug can't flood your DB with a 2 GB blob.

### Webhook never fires after writes
- `GNOSIS_MCP_WEBHOOK_URL` unset.
- The target resolves to a private / loopback / link-local IP. By default
  we refuse those (SSRF guard). Logs will say so. Set
  `GNOSIS_MCP_WEBHOOK_ALLOW_PRIVATE=true` for intentional loopback setups.
- Target returned non-2xx — we don't retry. Check your webhook server log.

---

## Web crawl

### "robots.txt disallows this URL"
Respect it. If you own the target and it's a config mistake, fix the
`robots.txt`. gnosis-mcp will not bypass.

### Crawl finishes with fewer pages than expected
- You passed `--max-pages N` (default 5000) and hit it.
- Many links point to non-HTML assets (PDFs without `[pdf]` extra, images).
- `--include` / `--exclude` globs filtered them out.
- Rate limiting by the target — retry with exponential backoff
  (currently manual).

### Re-crawl re-fetches everything
The ETag / Last-Modified / content-hash cache lives at
`~/.local/share/gnosis-mcp/crawl-cache.json`. If you deleted it, or
passed `--force`, you pay full cost.

---

## Performance

### Ingestion is slow
Profile:

1. `gnosis-mcp ingest --dry-run` first — shows the file list without
   writing.
2. Check if `--embed` is on. Embedding dominates ingest time if so.
3. Split into stages: `ingest` first, `embed` separately, so you can
   restart just the embedding pass if it fails.

### Search latency climbs over time
Vacuum the DB:

```sql
-- sqlite
VACUUM;
-- postgres
VACUUM ANALYZE documentation_chunks;
```

Or run `gnosis-mcp cleanup --days 30` to shrink the access-log table,
which can grow unbounded.

### Memory climbs in watch mode
Python's `weakref` isn't always enough with long-lived servers. Known
workaround: restart once a week via systemd `RuntimeMaxSec=` or Docker
`--restart unless-stopped` + `healthcheck`.

---

## Still stuck?

1. `gnosis-mcp check` — first 5 lines of output usually localise the
   problem.
2. `gnosis-mcp serve --transport stdio 2>/tmp/gnosis.log` — full log
   stream.
3. `GNOSIS_MCP_LOG_LEVEL=DEBUG gnosis-mcp …` — more detail.
4. Open an issue at
   [github.com/nicholasglazer/gnosis-mcp/issues](https://github.com/nicholasglazer/gnosis-mcp/issues)
   with the command you ran, the exact error, and the output of
   `gnosis-mcp check`.
