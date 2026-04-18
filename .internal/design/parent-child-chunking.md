---
title: "Parent-child chunking — v0.11 design"
category: docs
audience: all
status: design
last_verified: "2026-04-18"
relates_to:
  - docs/bench-experiments-2026-04-18.md
  - docs/tools.md
  - docs/config.md
---

# Parent-child chunking — v0.11 design

The chunk-size sweep in
[bench-experiments-2026-04-18](../bench-experiments-2026-04-18.md) showed
a trade-off that's fundamental, not solvable with tuning:

- **Small chunks** (500-1000 chars) rank precisely — BM25 finds the exact
  sentence that matches — but lose context. An LLM reading just "the
  retry interval is 30 s" doesn't know which service, which endpoint,
  which environment.
- **Large chunks** (2000-4000 chars) give the LLM context — one coherent
  section at a time — but dilute term density. Relevant passages compete
  with neighboring sentences for ranking weight.

Parent-child chunking resolves this by **decoupling the retrieval unit
from the context unit**. You retrieve at one granularity and return at
another.

## Concept

```
ingest:
  raw doc  →  split into child chunks (500 chars)  →  BM25 + embeddings
                                ↓ each child carries a pointer
                         parent chunk (2000 chars, a superset of the child)

search_docs:
  query  →  rank child chunks  →  top-k  →  return parent content
                                              (not the child's 500 chars)
```

The LLM sees 2000-char parents — enough context to understand the
retrieved material. BM25 ranks at the 500-char granularity — each chunk's
relevance signal is concentrated, not diluted.

Expected lift on our real-corpus golden set (extrapolating from the
chunk-size sweep): **+2 to +4 nDCG@10** over the 2000-char default.
Parent-child typically buys what separate small-chunk and large-chunk
runs *both* win at.

## Schema

Current `documentation_chunks` table (simplified):

```
chunk_id | file_path | chunk_index | content | embedding | …
```

New columns (nullable — backward compatible):

```
parent_chunk_index INTEGER  -- points to the coarse-grained chunk
is_child           BOOLEAN  -- "is this a retrieval-only row?"
```

On ingest:

1. Split the document at 2000 chars → call each result a *parent*, give
   it `parent_chunk_index = chunk_index`, `is_child = false`.
2. Within each parent, split at 500 chars → *children*, each carries the
   parent's index and `is_child = true`.
3. Write both parents and children. Children get embeddings; parents
   don't (saves ~75 % of embedding cost over a naive "embed everything"
   approach).

```
doc.md
├── chunk 0 (is_child=false, 2000 chars) ── parent, returned to LLM
│    ├── chunk 1 (is_child=true,  ~500 chars, parent=0) ── retrieval-only
│    ├── chunk 2 (is_child=true,  ~500 chars, parent=0)
│    ├── chunk 3 (is_child=true,  ~500 chars, parent=0)
│    └── chunk 4 (is_child=true,  ~500 chars, parent=0)
├── chunk 5 (is_child=false, 2000 chars) ── next parent
│    ├── chunk 6 (is_child=true,  ~500 chars, parent=5)
│    └── …
```

## Search path

`search_docs` picks up a new optional knob:

```
search_docs(query, limit=5, expand_to_parents=True)
```

Ranking runs on `is_child = true` rows (or all rows if feature is off).
After ranking, dedupe by `parent_chunk_index`: if two children of the
same parent score in the top-k, keep the higher-ranked one. Return
`limit` parents (not children).

Pseudo-SQL:

```sql
WITH child_hits AS (
  SELECT chunk_id, parent_chunk_index, file_path, rank()
  FROM documentation_chunks
  WHERE is_child = true
    AND matches(search_vector, :query)
  ORDER BY rank ASC
  LIMIT :limit * 3          -- overscan to allow dedup
),
dedup AS (
  SELECT DISTINCT ON (file_path, parent_chunk_index)
         chunk_id, parent_chunk_index, file_path, rank
  FROM child_hits
  ORDER BY file_path, parent_chunk_index, rank
)
SELECT p.file_path, p.title, p.content, d.rank
FROM dedup d
JOIN documentation_chunks p
  ON p.file_path = d.file_path
 AND p.chunk_index = d.parent_chunk_index
 AND p.is_child = false
ORDER BY d.rank
LIMIT :limit;
```

## Config

New env var:

- `GNOSIS_MCP_PARENT_CHILD=true` — turn on parent-child chunking. Default
  off in v0.11.0 (opt-in); promote to default in a later minor when
  we've benched more corpora.
- `GNOSIS_MCP_CHILD_CHUNK_SIZE=500` — retrieval granularity.
- `GNOSIS_MCP_CHUNK_SIZE=2000` — parent granularity (already exists,
  default updated in v0.11.0).

The two knobs are independent but should maintain roughly
`parent / child = 4`. Below 2 the parent barely adds context; above 8
the child chunks become too fragmented to rank well.

## Migration

Zero DB migration: the two new columns default NULL. Old indexes stay
valid (children have `is_child = true`, parents `is_child = false`,
pre-v0.11 rows all NULL and treated as parents by default). The
`search_docs` query gets an `AND (is_child = true OR is_child IS NULL)`
clause so existing corpora keep working while new ingests use the
parent-child split.

## Why not overlap instead

Overlapping chunks (10-20 % overlap between adjacent chunks) is the
classic mitigation for the "lose context at boundaries" problem. A
[Jan 2026 systematic study](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide)
on SPLADE + Mistral-8B / Natural Questions found overlap delivers
**zero measurable lift** and only increases indexing cost. Parent-child
explicitly separates the concerns — no overlap needed.

## Why not larger chunks

We tested 2200, 3000, 4000 chars — all below 2000's 0.8702 nDCG@10 on
the real-corpus sweep (see bench-experiments doc). Bigger chunks dilute
BM25 term density; parent-child dodges this by ranking on small chunks
while *displaying* bigger ones.

## Why not Anthropic's Contextual Retrieval instead

Anthropic's technique (Sept 2024 paper) prepends an LLM-generated
sentence of context to each chunk. Claimed -35 % retrieval failures on
average across their test corpora, but a Snowflake finance-RAG study
found -5.8 nDCG in one domain. Parent-child needs **no LLM call at
ingest**, works with any embedder, is dataset-agnostic, and composes
with contextual retrieval later if we want both.

## Implementation cost

- 1 day of work (schema fields, chunker, dedupe query)
- ~150 LOC
- 20-40 new tests (parent-child lifecycle, dedup boundary cases,
  backward compat)
- Docs update in `config.md`, `tools.md`, `bench-experiments`

## Acceptance criteria

- On the real-corpus golden set, `expand_to_parents=true` produces
  nDCG@10 ≥ 0.88 (up from 0.8702 at `chunk_size=2000`).
- On BEIR SciFact, zero regression vs current 0.6712 nDCG@10 (this one
  is already saturated by BM25; any uplift is gravy).
- Ingest time grows by at most 2× (more chunks, but embedder only runs
  on children so the dominant cost is unchanged).
- `GNOSIS_MCP_PARENT_CHILD=false` (default) path is byte-identical to
  v0.10.x output.

## Open questions

- Should children also carry embeddings, or only rank on BM25? (Probably
  BM25-only, to avoid 4× vector blow-up — but benchmark both.)
- What happens when a single paragraph crosses the parent boundary?
  Current proposal: parent splits only at H2/H3 boundaries (already how
  the existing chunker works), so this rarely happens.
- Multi-backend parity: the same logic has to work on Postgres
  (`documentation_chunks` on PG has the same schema + separate
  `documentation_links`). Confirmed: the two new columns add the same
  way on both backends.
