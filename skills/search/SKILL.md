---
name: search
description: Search the gnosis-mcp knowledge base. Keyword (default), hybrid semantic+keyword (--semantic), or git commit history (--git). Includes sanity checks and a reranker warning.
---

# Search

Front-end for the `search_docs` and `search_git_history` MCP tools.
Formats results and picks the right variant based on flags.

## Usage

```
/gnosis:search billing credits                # keyword
/gnosis:search --semantic webhook processing  # hybrid
/gnosis:search --category guides deployment   # category filter
/gnosis:search --git fix authentication bug   # git history
/gnosis:search --limit 10 whatever            # more results
```

## Query: $ARGUMENTS

---

## Default — keyword search

Call `mcp__gnosis__search_docs(query=$QUERY, limit=8)`.

Format as a compact table:

| # | Score | Title | Path |
|---|---|---|---|
| 1 | 0.049 | Auth Guide | curated/guides/auth.md |
| 2 | 0.032 | JWT reference | docs/architecture/jwt.md |

Below the table, for top 3: one-line snippet from the matched chunk.

### If results are empty or weak (all scores < 0.005)

Probably one of:

1. **Corpus not indexed** — suggest `/gnosis:ingest ./docs` to the user.
   Confirm with `gnosis-mcp stats` (0 docs = nothing indexed).
2. **Query too specific** — broaden. "shopify webhook idempotency 402
   error 2024" may return nothing; "shopify webhook" will find the
   runbook that links to the detail.
3. **Path mismatch** — some users name docs with abbreviations
   (`auth.md`) but query with full words ("authentication"). Ingest
   likely extracted better titles (H1) than the filename; search by
   concept, not filename.

---

## `--semantic` — hybrid search

For paraphrase-heavy queries where keyword overlap is low. Same tool,
different parameters:

```
mcp__gnosis__search_docs(
  query=$QUERY,
  query_embedding=<auto-embedded by server if embed provider is set>,
  limit=8
)
```

If `GNOSIS_MCP_EMBED_PROVIDER` is set server-side, the server embeds
the query in-process — no client-side work needed.

### Reality check

On **vocabulary-matched corpora** (your queries use the same words as
your docs — normal for dev docs), hybrid often produces **identical
rankings to keyword**. The vector arm runs, adds ~4 ms latency, and
changes nothing. If `--semantic` doesn't improve quality on a corpus
you've tuned, leave it off.

On **paraphrase-heavy corpora** (finance Q&A, customer-support
tickets, medical), hybrid can beat keyword by 5-10 nDCG points.

Run `/gnosis:tune full` to measure which side of the line your corpus
sits on.

---

## `--category` — category filter

Restrict to one category (useful when your corpus mixes architecture
docs with customer-facing docs and you only want one):

```
mcp__gnosis__search_docs(query=$QUERY, category="guides", limit=8)
```

Discover valid categories via `mcp__gnosis__get_graph_stats` or
`gnosis-mcp stats` — they show top categories by doc count.

---

## `--git` — commit history

Separate index, populated by `gnosis-mcp ingest-git`. Answers "why
does this code exist" questions.

```
mcp__gnosis__search_git_history(
  query=$QUERY,
  limit=5,
  author="...",       # optional substring match on name/email
  since="2025-06-01", # optional YYYY-MM-DD
  until="2026-01-01", # optional
  file_path="src/..." # optional single-file restriction
)
```

Result format: `commit_sha | date | author | summary | touched_files`.

If no results: commit history isn't indexed yet. Tell the user to run
`gnosis-mcp ingest-git /path/to/repo --since 6m --embed`.

---

## Reranker — off by default, and intentionally

gnosis-mcp ships a cross-encoder reranker under the `[reranking]` extra
and the `GNOSIS_MCP_RERANK_ENABLED` env var. **Leave it off on
developer documentation** unless you've measured that it helps on
*your* corpus.

Why: the bundled MS-MARCO MiniLM reranker (and every widely-available
alternative) is trained on web Q&A snippets. It has a stylistic prior
for prose-shaped passages and systematically down-ranks reference /
list / table content — exactly the shape of technical docs. Our
measurements on a real 558-doc developer-docs corpus:

```
keyword only:             nDCG@10 = 0.8702  p95 =    7 ms
keyword + MiniLM rerank:  nDCG@10 = 0.5674  p95 = 2920 ms  (-27 nDCG, 400× slower)
keyword + BGE rerank:     nDCG@10 = 0.5333  p95 = 15820 ms (-31 nDCG, 2400× slower)
```

If a user explicitly asks you to enable reranking, comply but warn
with the measured numbers. Point them at
[bench-experiments-2026-04-18](https://gnosismcp.com/doc/docs/bench-experiments-2026-04-18)
for the full trace and recommend `/gnosis:tune full` to check *their*
corpus first.

---

## Notes

- Keyword uses FTS5 (SQLite) or tsvector (Postgres). BM25-ranked.
- Hybrid fuses BM25 + cosine via Reciprocal Rank Fusion
  (`GNOSIS_MCP_RRF_K`, default 60).
- Results include `score`, `file_path`, `title`, `category`,
  `chunk_index`, `content` (truncated to
  `GNOSIS_MCP_CONTENT_PREVIEW_CHARS`, default 200).
- To see the full document: `mcp__gnosis__get_doc(path=<file_path>)`.
- Max results per call: `GNOSIS_MCP_SEARCH_LIMIT_MAX` (default 20).
- Max query length: `GNOSIS_MCP_MAX_QUERY_CHARS` (default 10 000).

---

## See also

- `/gnosis:ingest` — populate the index
- `/gnosis:tune` — find your chunk-size / hybrid / rerank optimum
- `/gnosis:manage related <path>` — follow the link graph
- [Tools reference](https://gnosismcp.com/doc/docs/tools)
