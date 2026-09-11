---
title: Configuration Reference
category: docs
audience: all
relates_to:
  - README.md
  - docs/tools.md
  - docs/cli.md
  - docs/rest-api.md
---

# Configuration Reference

Every knob gnosis-mcp exposes lives under an environment variable prefixed
`GNOSIS_MCP_*`. There is no TOML/YAML config file. Philosophy:

- **Zero config is the default** — running `gnosis-mcp serve` with no env set
  boots SQLite at `~/.local/share/gnosis-mcp/docs.db` and serves stdio.
- **Every override is an env var** so you can configure inside Docker,
  `systemd`, Claude Desktop / Cursor configs, or `direnv` with the same
  primitive.
- **Secrets stay in env** — never in the DB, never on disk.

Variables are grouped below by what they control.

---

## Core

### `GNOSIS_MCP_BACKEND`

`auto | sqlite | postgres` — default **`auto`**.

`auto` inspects `GNOSIS_MCP_DATABASE_URL` / `DATABASE_URL`: a `postgresql://`
URL selects Postgres, anything else (or unset) selects SQLite.

### `GNOSIS_MCP_DATABASE_URL`

Database connection string. Falls back to `DATABASE_URL` if unset.

- SQLite: `sqlite:///absolute/path/to/docs.db` (or leave unset for the default
  XDG-compliant path).
- Postgres: standard libpq URL, e.g. `postgresql://user:pass@host:5432/db`.

### `GNOSIS_MCP_WRITABLE`

`true | false` — default **`false`**.

Gate for the three write tools (`upsert_doc`, `delete_doc`, `update_metadata`).

When false, those three tools are **withdrawn from `tools/list`** — a
read-only client is never handed a tool it cannot call, and sees six tools
rather than nine, three of which could only ever fail. A call to one of them
then fails as an _unknown tool_, because as far as the server's advertised
surface is concerned it does not exist. No data is mutated either way.

The in-call check is unchanged: with writes enabled the tools are advertised,
and a call that is still refused for another reason (for example
`update_metadata` with no fields to update) reports MCP `isError: true`. Tool
failures carry their payload as the error text of a failed result, not as a
`{"error": ...}` body inside a _successful_ one.

This changed in v0.15.0. Before that, all nine tools were advertised
regardless and a refused write returned a `{"error": ...}` payload inside a
successful result — indistinguishable from data, and impossible for a client
to retry or gate on uniformly.

### `GNOSIS_MCP_LOG_LEVEL`

`DEBUG | INFO | WARNING | ERROR | CRITICAL` — default **`INFO`**.

---

## Transport

### `GNOSIS_MCP_TRANSPORT`

`stdio | streamable-http | sse` — default **`stdio`**.

Stdio is the MCP-client default; streamable-http exposes a `/mcp` endpoint
you can deploy publicly or on a network; sse is a legacy MCP transport.

### `GNOSIS_MCP_HOST`

Default **`127.0.0.1`**. Bind address for the HTTP transports. Use `0.0.0.0`
to accept connections from other hosts (and remember to put an auth layer
in front — see `GNOSIS_MCP_API_KEY`).

### `GNOSIS_MCP_PORT`

Default **`8000`**. Port for the HTTP transport.

---

## Ingestion & chunking

### `GNOSIS_MCP_CHUNK_SIZE`

Default **`2000`**. Minimum `500`. Unit: **characters** (not tokens, not
words).

Target character length for chunks. Chunks never split inside fenced code
blocks or markdown tables; splits prefer H2, then H3/H4, then paragraph
boundaries.

Rough conversion: 2000 chars ≈ 600 tokens ≈ 300-350 English words.

**Why 2000.** On a real 558-doc developer-docs corpus with 25 hand-written
golden queries, we swept chunk sizes 1000 → 4000 chars in steps. The peak
sits on an **1800-2000 char plateau** (0.8702 nDCG@10); both smaller
(fragments sections, dilutes BM25 term density) and larger (merges
unrelated content, same dilution in the other direction) score worse.
2000 is chosen over 1800 as the high end of the plateau — same quality,
fewer chunks, faster ingest. Full sweep in
[bench-experiments-2026-04-18](bench-experiments-2026-04-18.md).

Raise it to **3000-4000** for long-form prose (blog posts, ADRs) where
sections are naturally bigger. Lower to **1000-1500** for API references
or rows-of-tables content where each fact is short and standalone.

### `GNOSIS_MCP_MAX_DOC_BYTES`

Default **`50_000_000`** (50 MB).

Maximum content size accepted by `upsert_doc`. Prevents accidentally
attempting to index a 2 GB SQL dump.

### `GNOSIS_MCP_CONTENT_PREVIEW_CHARS`

Default **`200`**. Minimum `50`.

Length of the preview slice returned by `search_docs`. Set larger if you want
chunks returned nearly whole; smaller if you're paying per-token downstream.

### `GNOSIS_MCP_INGEST_EXCLUDE`

Default **empty** (exclude nothing). Comma-separated root-relative POSIX path
prefixes.

Files matching an entry are skipped by `ingest`, `diff` and `prune`. A
trailing slash excludes a whole directory (`".internal/audit-logs/"`); a bare
entry excludes one file (`"llms-full.txt"`). The exclusion counts as "not on
disk" for `prune`, so a file that was indexed _before_ the exclude was
configured is removed on the next prune instead of lingering searchable.

Use this for files that exist on disk but are not documentation — raw audit
logs, generated full-text dumps:

```bash
GNOSIS_MCP_INGEST_EXCLUDE=".internal/audit-logs/,llms-full.txt" \
  gnosis-mcp serve --watch /path/to/knowledge
gnosis-mcp prune /path/to/knowledge   # one-time: drop what was indexed earlier
```

An explicitly empty value (`GNOSIS_MCP_INGEST_EXCLUDE=`) means "exclude
nothing" and is distinct from unset.

---

## Search

### `GNOSIS_MCP_SEARCH_LIMIT_MAX`

Default **`20`**. Minimum `1`.

Hard ceiling for the `limit` param on `search_docs`. Clients can ask for
larger numbers but get clamped.

### `GNOSIS_MCP_MAX_QUERY_CHARS`

Default **`10_000`**.

Rejects pathological queries early. Legitimate semantic queries are rarely
over a couple hundred characters.

### `GNOSIS_MCP_RRF_K`

Default **`60`**.

Constant in the Reciprocal-Rank-Fusion formula used by hybrid search:
`score = Σ 1 / (k + rank_i)`. Higher `k` flattens the rank curve and lets
vector scores contribute more relative to BM25. Typical values are 30–120.

### `GNOSIS_MCP_COLLAPSE_BY_DOC`

`true | false` — default **`false`**.

Post-processes the top-K results to keep at most one chunk per document (its
highest-scoring one), so a single popular document cannot fill the whole result
list. Opt-in so result shapes stay stable for existing callers.

### `GNOSIS_MCP_FTS5_TITLE_WEIGHT` / `GNOSIS_MCP_FTS5_CONTENT_WEIGHT`

Floats — defaults **`10.0`** and **`1.0`**. _SQLite only._

The `bm25()` column weights, i.e. how much a title match counts against a body
match. The defaults keep the historical 10:1 ratio; set both to `1.0` for uniform
scoring.

### `GNOSIS_MCP_MMR_LAMBDA`

Float — default **`1.0`** (disabled).

Below `1.0`, the top-K candidates are re-ranked with Maximal Marginal Relevance
(Carbonell & Goldstein, 1998) to trade relevance for diversity: `1.0` is pure
relevance, `0.0` pure diversity, and `0.6` a common middle ground for developer
docs. Requires an active embedder — it falls back to the original order when
embedding fails.

### `GNOSIS_MCP_SEARCH_FUNCTION`

_(Postgres only.)_ Name of a user-defined function that `search_docs` delegates
to instead of the built-in path — useful for plugging in experimental ranking
without forking the server. It is called as:

```sql
SELECT * FROM your_function(
  p_query_text := $1::text,  p_embedding := $2::vector,
  p_categories := $3::text[], p_limit     := $4::integer)
```

`p_embedding` is `NULL` when no embedding is available and `p_categories` is
`NULL` unless a category filter is set, so give both defaults. It must return the
same columns as the built-in search functions:
`(file_path text, title text, content text, category text,
combined_score double precision)`.

---

## Embeddings

### `GNOSIS_MCP_EMBED_PROVIDER`

`local | openai | ollama | custom` — unset by default (no auto-embedding).

- `local` — ONNX Runtime CPU inference. Requires the `[embeddings]` extra.
- `openai` — OpenAI-compatible HTTP API.
- `ollama` — an Ollama-compatible HTTP API.
- `custom` — any OpenAI-schema HTTP endpoint (set `GNOSIS_MCP_EMBED_URL`).

### `GNOSIS_MCP_EMBED_MODEL`

Model name. The general default is `text-embedding-3-small` (OpenAI, 1536-dim).
When `GNOSIS_MCP_EMBED_PROVIDER=local`, the default switches to
`MongoDB/mdbr-leaf-ir` (384-dim, 23 MB quantized, Apache 2.0, auto-downloaded
on first run with an HTTPS + SHA-256 checksum assertion).

### `GNOSIS_MCP_EMBED_DIM` / `GNOSIS_MCP_EMBEDDING_DIM`

Output dimension. Both spellings accepted. When unset, the server asks the
provider to report it once at start-up.

### `GNOSIS_MCP_EMBED_URL`

Custom / remote provider endpoint (OpenAI-schema `/embeddings` POST).

### `GNOSIS_MCP_EMBED_API_KEY`

Bearer token for the remote provider.

### `GNOSIS_MCP_EMBED_BATCH_SIZE`

Default **`50`**. Minimum `1`. Balances provider rate limits against ingest
throughput.

---

## Reranking

### `GNOSIS_MCP_RERANK_ENABLED`

`true | false` — default **`false`**.

Opt-in cross-encoder reranker (22M-param ONNX) applied to the top candidates
from `search_docs` before returning. Requires the `[reranking]` extra.

Typical cost: ~20 ms per query for the default top-20 pool on laptop CPU.

### `GNOSIS_MCP_RERANK_MODEL`

Default **`cross-encoder/ms-marco-MiniLM-L6-v2`**. The cross-encoder to download
and run. It must be a genuine cross-encoder (a `BertForSequenceClassification`
style model that scores a query/passage pair) — pointing it at an embedding model
produces no usable scores. A model that cannot be fetched is reported at startup
and searches then return unranked results, so verify it on your corpus.

### `GNOSIS_MCP_RERANK_POOL`

Integer — default **`20`**. How many candidates are fetched and re-scored before
the top `limit` are returned. A larger pool is more accurate and slower.

---

## Web crawl

### `GNOSIS_MCP_CRAWL_EXTRACT_TIMEOUT_S`

Default **`30`**. Seconds before we abandon the HTML-to-markdown extraction
for a given page. Prevents pathological pages from freezing the crawl loop.

---

## Webhooks

### `GNOSIS_MCP_WEBHOOK_URL`

Fires a fire-and-forget `POST` on every write tool. Body is a small JSON
envelope: `{tool, path, ts}`. Useful for invalidating downstream caches.

### `GNOSIS_MCP_WEBHOOK_TIMEOUT`

Default **`5`**. Seconds. Minimum `1`.

### `GNOSIS_MCP_WEBHOOK_ALLOW_PRIVATE`

`true | false` — default **`false`**.

By default the webhook target must resolve to a public IP. Requests to
private, loopback, link-local, multicast, or reserved addresses are refused
with a warning log. Set `true` for intentional loopback CI setups.

---

## REST API

Enable with the `--rest` flag on `gnosis-mcp serve` or `GNOSIS_MCP_REST=true`.
Lives alongside MCP on the same HTTP port. See [rest-api.md](rest-api.md)
for the endpoint reference.

### `GNOSIS_MCP_REST`

`true | false` — default **`false`**.

### `GNOSIS_MCP_API_KEY`

Optional. When set, every endpoint (except `/health`) requires
`Authorization: Bearer <key>`. Comparison is timing-safe.

### `GNOSIS_MCP_PUBLIC_PATHS`

**Not implemented — reading this variable has no effect.** It is documented
here only so the absence is explicit.

`/health` is the one unauthenticated path, always. Every other route,
including anything under `/api/` and `POST /v1/embed`, requires
`Authorization: Bearer <key>` whenever `GNOSIS_MCP_API_KEY` is set. There is
no way to add a second public path by configuration today.

The setting was documented in the pre-launch docs commit but the env-var
read was never written: `GnosisMcpConfig` has no `public_paths` field, and
the auth middleware is constructed as `ApiKeyMiddleware(app, config.api_key)`
with no `public_paths` argument, so it falls back to its built-in
`("/health",)` default. (The middleware does accept a `public_paths`
parameter, so the hook exists for a future release — it is simply never
supplied.) If you need extra probes to bypass auth, terminate them at your
reverse proxy rather than at gnosis-mcp.

### `GNOSIS_MCP_CORS_ORIGINS`

Comma-separated origins, or `*`. No CORS response headers unless set.

---

## Access log

### `GNOSIS_MCP_ACCESS_LOG`

`true | false` — default **`true`**.

When enabled, records which documents are retrieved via `search_docs`
(top 3 results) and `get_doc`. Used by `get_context` to surface
frequently-read documentation. Writes to `search_access_log` table; set to
`false` to disable tracking entirely.

Each row also carries the MCP client that made the call (from the session's
`initialize` handshake) and the token counts that back [`savings`](cli.md#savings);
[`usage`](cli.md#usage) reads all of it, including **misses** — a `search_docs`
call that matched nothing is logged with an empty `file_path`, so a query the
index could not answer is still a row.

If the table predates those columns, `init-db` retrofits them (`ALTER TABLE …
ADD COLUMN IF NOT EXISTS`) on the next run. Until it does, logging succeeds with
no error while `client`/token attribution stays empty — silently. Re-running
`init-db` after an upgrade is always safe: every statement is idempotent.

---

## Postgres-specific

### `GNOSIS_MCP_SCHEMA`

Default **`public`**. Alternate schema for all gnosis-mcp tables.

### `GNOSIS_MCP_CHUNKS_TABLE`

Default **`documentation_chunks`**. Single name or comma-separated list —
with multiple tables, search queries use `UNION ALL`. All tables must share the
same schema (identical column names and types), and **writes** (`ingest`,
`upsert_doc`, `delete_doc`, `update_metadata`) target the **first** table in the
list.

### `GNOSIS_MCP_LINKS_TABLE`

Default **`documentation_links`**.

### `GNOSIS_MCP_POOL_MIN` / `GNOSIS_MCP_POOL_MAX`

asyncpg connection-pool bounds. Defaults **`1`** / **`3`**.

### Column overrides (`GNOSIS_MCP_COL_*`)

When connecting to an existing schema with non-standard column names, map
each field:

| Env var                        | Logical column          |
| ------------------------------ | ----------------------- |
| `GNOSIS_MCP_COL_FILE_PATH`     | `file_path`             |
| `GNOSIS_MCP_COL_CHUNK_INDEX`   | `chunk_index`           |
| `GNOSIS_MCP_COL_TITLE`         | `title`                 |
| `GNOSIS_MCP_COL_CATEGORY`      | `category`              |
| `GNOSIS_MCP_COL_CONTENT`       | `content`               |
| `GNOSIS_MCP_COL_AUDIENCE`      | `audience`              |
| `GNOSIS_MCP_COL_TAGS`          | `tags`                  |
| `GNOSIS_MCP_COL_EMBEDDING`     | `embedding`             |
| `GNOSIS_MCP_COL_TSV`           | `search_vector`         |
| `GNOSIS_MCP_COL_SOURCE_PATH`   | `source_path` (links)   |
| `GNOSIS_MCP_COL_TARGET_PATH`   | `target_path` (links)   |
| `GNOSIS_MCP_COL_RELATION_TYPE` | `relation_type` (links) |

Every identifier is validated against `^[a-zA-Z_][a-zA-Z0-9_]*$` at startup
to prevent SQL injection via config.

---

## Precedence

1. Explicit env var.
2. Derived default (e.g. `GNOSIS_MCP_BACKEND=auto` inferring from URL).
3. Hard-coded default.

There is no file-based override layer. Restart the server to pick up env
changes.

---

## See also

- [CLI reference](cli.md)
- [MCP tools](tools.md)
- [REST API](rest-api.md)
