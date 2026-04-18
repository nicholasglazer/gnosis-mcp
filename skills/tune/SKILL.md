---
name: tune
description: Find the chunk-size and retrieval config that maximizes quality on YOUR corpus. Sweeps chunk sizes, runs a golden-query set, reports nDCG / MRR / Hit@5. Use after first ingest or whenever your corpus changes shape significantly.
disable-model-invocation: true
---

# Tune

Every RAG system has a distribution where it breaks. The only way to
know whether gnosis-mcp's defaults are right for *your* corpus is to
measure them against *your* queries. This skill runs that measurement.

## Usage

```
/gnosis:tune                       # Quick sweep (5 chunk sizes, keyword mode)
/gnosis:tune full                  # Extended sweep (keyword + hybrid + rerank on/off)
/gnosis:tune --golden ./q.jsonl    # Use a specific golden-query file
```

## Mode: $ARGUMENTS

---

## Prerequisites

You need:

1. A corpus — anywhere on disk. Will be passed to `gnosis-mcp ingest`.
2. A golden-query file — one JSON object per line:

   ```json
   {"query": "how does our auth work", "expected_paths": ["docs/auth", "architecture/auth"]}
   {"query": "stripe webhook failure runbook", "expected_paths": ["runbooks/stripe"]}
   ```

   `expected_paths` uses substring match against the returned `file_path`,
   case-insensitive. Generous enough that you don't need exact path
   memorization.

20 hand-written queries is enough to get signal. 50 is plenty.

---

## Quick sweep (default)

Runs `gnosis-mcp ingest` 5 times with different chunk sizes, scoring
each with your golden set. Keyword mode only (fast, no embedding cost).

```bash
# Default path if none given: ./docs + ./golden.jsonl
CORPUS=${CORPUS:-./docs}
GOLDEN=${GOLDEN:-./golden.jsonl}

for size in 1000 1500 2000 2500 3000; do
  uv run --with 'gnosis-mcp[embeddings] @ gnosis-mcp' \
    python tests/bench/bench_real_corpus.py \
      --corpus "$CORPUS" --golden "$GOLDEN" \
      --modes keyword --chunk-size $size \
      --out bench-results/tune-chunk${size}.json
done
```

(If gnosis-mcp was installed via pip rather than from source, invoke
`bench_real_corpus.py` from the repo you cloned, and drop the
`uv run --with '... @ .'` prefix.)

Expected runtime: 5–10 minutes per size on a typical laptop (ingest is
the dominant cost; scoring itself is sub-second).

Output table:

```
chunk  chars │ nDCG@10 │ MRR    │ Hit@5  │ p95      │ ingest
────────────┼─────────┼────────┼────────┼──────────┼────────
       1000 │ 0.8557  │ 0.8067 │ 0.92   │ 30 ms    │ 592 s
       1500 │ 0.8529  │ 0.7967 │ 0.92   │  7 ms    │ 234 s
       2000 │ 0.8702  │ 0.7933 │ 0.92   │  7 ms    │ 210 s   ← peak
       2500 │ 0.8602  │ 0.7880 │ 0.92   │  7 ms    │ 195 s
       3000 │ 0.8459  │ 0.7880 │ 0.92   │  7 ms    │ 182 s
```

Pick the chunk size with the best nDCG@10 that doesn't blow your
ingest-time budget. Persist it:

```bash
# In your shell profile / .env
export GNOSIS_MCP_CHUNK_SIZE=2000
```

If multiple sizes tie at the top (plateau), pick the **larger** one —
same quality, fewer chunks, faster ingest.

---

## Full sweep (`full`)

Adds hybrid mode and optional reranker A/B — ~30-40 minutes depending
on corpus size and whether `[reranking]` is installed.

```bash
for size in 1500 2000 3000; do
  for mode in keyword hybrid hybrid+rerank; do
    uv run --with 'gnosis-mcp[embeddings,reranking] @ gnosis-mcp' \
      python tests/bench/bench_real_corpus.py \
        --corpus "$CORPUS" --golden "$GOLDEN" \
        --modes "$mode" --chunk-size $size \
        --out "bench-results/tune-${mode//+/_}-${size}.json"
  done
done
```

### What to read from the output

1. **nDCG delta between keyword and hybrid**: if < 0.02, your corpus is
   vocabulary-matched (queries share exact terms with docs). Dense
   retrieval adds latency without lift — leave hybrid off.

2. **nDCG delta when reranker is added**: on dev docs specifically, we
   measure -27 nDCG (!). If you see a similar drop, your corpus has
   the same distribution problem — disable
   `GNOSIS_MCP_RERANK_ENABLED`. If it's +3-10 on your corpus, keep it
   on.

3. **Chunk-size peak location**: tells you the typical topic-coherent
   block length in your corpus. API-reference-heavy corpora peak
   lower (1000-1500 chars). Long-form prose peaks higher (2500-3000).

---

## Programmatic golden-set from existing access logs

If you've been using gnosis-mcp for a while, real queries are already
logged. Generate a seed golden file from them:

```bash
sqlite3 ~/.local/share/gnosis-mcp/docs.db \
  "SELECT DISTINCT query FROM search_access_log
   WHERE timestamp > date('now', '-30 days')
   ORDER BY count(*) DESC LIMIT 30;" \
  | awk '{print "{\"query\":\""$0"\", \"expected_paths\": []}"}' > golden-seed.jsonl
```

Then fill in `expected_paths` by hand — 5 minutes of work, gives you a
golden set grounded in how you actually use the system.

---

## Automate the winner

After picking a chunk size and reranker/hybrid choice, persist it so
every `gnosis-mcp ingest` (manual or via `--watch`) uses the tuned
settings:

```bash
# Persistent across processes
export GNOSIS_MCP_CHUNK_SIZE=2000
export GNOSIS_MCP_RERANK_ENABLED=false  # if tune showed it hurts

# Re-ingest with the new config
gnosis-mcp ingest ./docs --embed --wipe
```

---

## When to re-tune

- Corpus grows 2× or more
- You add a fundamentally different content type (e.g., API references
  added to a prose-only corpus, or vice versa)
- You switch embedder (`GNOSIS_MCP_EMBED_MODEL`) — the semantic side
  of hybrid now behaves differently
- After a new release of gnosis-mcp that touched chunking or fusion

Otherwise: tune once per year. It's not free but it's not frequent.

---

## See also

- [bench-experiments-2026-04-18](https://gnosismcp.com/doc/docs/bench-experiments-2026-04-18)
  — our own tune results with the methodology that informed these
  defaults
- [how-we-measure-search](https://gnosismcp.com/doc/docs/how-we-measure-search)
  — what these metrics mean, in plain English
- `/gnosis:ingest` — re-ingest after you've picked the winner
