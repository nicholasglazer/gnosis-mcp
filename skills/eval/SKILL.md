---
name: eval
description: Measure retrieval quality — Hit@5, MRR, Precision@5 on a fixed fixture set, or Hit@5/MRR/nDCG@10 on your own corpus via the real-corpus benchmark. Regression tracking against a saved baseline, plain-English interpretation, and tuning pointers when numbers look off. Use after every ingest or config change.
---

# Eval

`gnosis-mcp eval` in ~10 lines of wrapper logic. Reports retrieval
quality, compares to last known numbers, and points at `/gnosis:tune` if
anything looks regressed.

**Know what you are measuring.** `gnosis-mcp eval` does *not* score your
corpus. It loads nine hardcoded sample documents (`SAMPLE_DOCS` +
`SAMPLE_GIT_HISTORY_DOCS` from the repository's `tests/eval/` fixtures)
into a temporary database and ignores `GNOSIS_MCP_DATABASE_URL`, so it
prints identical numbers no matter what you have indexed. It is a harness
smoke test, not a measurement of your docs. To score your own corpus, run
the real-corpus benchmark (Step 1b) — that path is corpus-specific and
reports nDCG@10, which `gnosis-mcp eval` never emits.

Different from `/gnosis:tune`: tune **sweeps** configurations looking
for the best chunk size / embedder / rerank combo. Eval just reports
current numbers. Run eval often (after each ingest, whenever the
corpus changes). Run tune occasionally (after corpus shape change,
new embedder, weekend of experimentation).

## Usage

```
/gnosis:eval                    # full run — print numbers + interpret + compare
/gnosis:eval quick              # numbers only, no interpretation
/gnosis:eval save               # save current result as new baseline
/gnosis:eval diff               # compare current to last saved baseline
```

## Mode: $ARGUMENTS

---

## Step 1 — run the harness

```bash
gnosis-mcp eval --json
```

Parses to:
```json
{
  "cases": 10,
  "hit_rate_at_k": 1.0,
  "mrr": 1.0,
  "mean_precision_at_k": 0.75,
  "k": 5
}
```

Those five keys are the whole contract — there is no `ndcg_at_10` in this
command's output, and no `queries` / `hit_at_5` / `mean_precision_at_5`
(the real names carry `_at_k` plus the separate `k` field).

If the command errors, the cause is almost always a missing repository
checkout: `eval` imports its fixtures from `tests/eval/`, so a plain
`pip install` (no `tests/` directory) exits `1` with an install-from-source
hint. It does **not** need the `[embeddings]` extra, a golden file, or a
populated database — it builds its own fixture in a temp DB. Don't
proceed with empty numbers — fail loudly.

## Step 1b — real-corpus numbers (optional, corpus-specific)

When you want numbers that actually describe the user's docs:

```bash
python tests/bench/bench_real_corpus.py \
    --corpus /path/to/docs \
    --golden tests/bench/golden-knowledge.jsonl
```

`--corpus` is the markdown root to ingest, `--golden` a JSONL file of
`{"query": "...", "expected_paths": ["docs/x.md"]}` lines. Extra flags:
`--modes`, `--k`, `--rerank-n`, `--title-prepend`, `--chunk-size`. This
one reports `hit_at_5`, `hit_at_10`, `mrr`, `ndcg_at_10`, and `p95_ms`
per mode — so it is where an nDCG comparison belongs. Needs the
`[embeddings]` (and optionally `[reranking]`) extras.

If the user supplies no golden set, ask for one before running it; inventing
expected paths would make the numbers meaningless.

## Step 2 — interpret

Report as a compact table, using whatever Step 1 or Step 1b actually
emitted. The values below are a worked example from a real-corpus run:

| Metric | Value | Meaning |
|---|---|---|
| Hit@K | **0.92** | 9 of 10 queries find the right doc in the top K results |
| MRR | **0.79** | On average the right doc ranks ~1.3 in the list (1 / 0.79) |
| Precision@K | **0.67** | Of the top 5 results, 67% are relevant |
| nDCG@10 | **0.87** | Ranking quality — Step 1b only; 1.0 is perfect, random baseline is ~0.15 |

A Step 1 fixture run is not worth interpreting this way: it reports
`hit_rate_at_k` 1.0, `mrr` 1.0 and `mean_precision_at_k` 0.75 at `k` 5 on
every corpus — all ten cases hit. Say that plainly instead of presenting
it as a quality score for the user's docs.

**Interpretation thresholds** (rough heuristics, corpus-dependent):

- **Hit@5 ≥ 0.85** → healthy. Users rarely need to read past position 5.
- **Hit@5 0.70-0.85** → acceptable. Keyword-saturated corpus likely; little room to grow without changing the eval set.
- **Hit@5 < 0.70** → probably a corpus or chunking problem. Run `/gnosis:tune` to sweep chunk sizes.
- **MRR / Hit@5 ratio < 0.80** → relevant docs exist in top-5 but ranked too low. Try title-prepending or reranking (`/gnosis:tune` covers both experiments).
- **nDCG@10 ≥ 0.85 with Hit@5 = 0.92** on a real-corpus run matches our published 558-doc dev-docs baseline — you're in the same regime as gnosis-mcp's own corpus.

## Step 3 — compare to baseline (mode: default, diff, save)

Baseline lives at `~/.local/share/gnosis-mcp/eval-baseline.json`.

**If baseline exists** (default + diff modes) — illustrative values below;
substitute what the runs actually emitted:

```
Metric       Now       Last (2026-04-18)   Δ
Hit@K        0.9200    0.9200              —
MRR          0.7933    0.7933              —
P@K          0.6680    0.6680              —
```

The baseline stores exactly what Step 1 emitted (`cases`, `hit_rate_at_k`,
`mrr`, `mean_precision_at_k`, `k`) — a fixture baseline therefore reads
`1.0` / `1.0` / `0.75`, not the numbers shown above. A Step 1b run instead
records that mode's `hit_at_5`, `mrr` and `ndcg_at_10`. Keep the two sources
labelled and do not mix them in one baseline: a fixture `hit_rate_at_k`
diffed against a real-corpus `ndcg_at_10` means nothing.

Flag any Δ worse than **-2 points** in red and explicitly ask the
user if the regression is expected. "Expected" reasons: new corpus
shape, different chunk size, swapped embedder. "Not expected":
accidental regression → investigate before committing the drop.

**If no baseline exists** (default mode only — first-time run):

```
No baseline found. Save current numbers as baseline? (y/N)
```

On `y`, write the JSON to `~/.local/share/gnosis-mcp/eval-baseline.json`
and confirm. On `N`, skip — user runs `/gnosis:eval save` later when
they're happy with a specific state.

**`save` mode**: unconditionally overwrite the baseline with current
numbers. Useful after an intentional improvement (e.g., `/gnosis:tune`
found a better chunk size, user re-ingested, wants to lock in the new
baseline).

## Step 4 — recommendation (default mode)

Based on the numbers, point at the next action. These triggers assume a
Step 1b real-corpus run, or a fixture run diffed against a saved fixture
baseline — a fresh Step 1 run sits at `hit_rate_at_k` 1.0 and fires none of
them, so do not invent a regression story for it:

| State | Next action |
|---|---|
| Everything green, no regression | "Numbers look healthy. Run `/gnosis:ingest <path> --prune` after any doc change to keep them that way." |
| Hit@5 dropped > 2 points | "Regression. Run `/gnosis:status diag` to rule out corruption, then `git diff` any recent ingest or config changes." |
| Hit@5 healthy but MRR weak | "Ranking is the weak link. `/gnosis:tune` can test title-prepending — sometimes worth +3 MRR points on keyword-saturated corpora." |
| Hit@5 < 0.70 | "Chunk size or corpus shape issue. `/gnosis:tune` will sweep chunk sizes 1000-4000 and report the optimum — ~10 min runtime." |
| No regression but first time | "Run `/gnosis:eval save` to lock these as your baseline. Future runs will diff against this." |

## When to skip `/gnosis:eval`

- **Any question about the user's actual corpus** → `gnosis-mcp eval` cannot
  answer it; go to Step 1b.
- **BEIR-style public benchmark** → use `tests/bench/bench_beir.py` instead. That's external validity; eval is in-distribution validity.
- **End-to-end MCP round-trip timing** → `tests/bench/bench_mcp_e2e.py`.
- **Comparison across embedders** → `scripts/bench-embedders.sh` for the full matrix.

## What the numbers mean for non-experts

See [`docs/how-we-measure-search.md`](../../docs/how-we-measure-search.md)
for a plain-English explainer of Hit@K / MRR / nDCG (if that doc
exists in this corpus; otherwise point at the gnosismcp.com version:
https://gnosismcp.com/docs/how-we-measure-search).
