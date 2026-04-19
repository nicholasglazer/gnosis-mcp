---
name: eval
description: Measure retrieval quality on your corpus — Hit@5, MRR, nDCG@10, Precision@5. Thin wrapper around `gnosis-mcp eval` with regression tracking against a saved baseline, plain-English interpretation, and tuning pointers when numbers look off. Use after every ingest or config change.
---

# Eval

`gnosis-mcp eval` in ~10 lines of wrapper logic. Reports retrieval
quality against your golden queries, compares to last known numbers,
and points at `/gnosis:tune` if anything looks regressed.

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
  "queries": 10,
  "hit_at_5": 1.000,
  "mrr": 0.950,
  "mean_precision_at_5": 0.668,
  "ndcg_at_10": 0.871
}
```

If the command errors (no `[embeddings]` extra, no golden file, empty
DB), explain the exact cause and the fix. Don't proceed with empty
numbers — fail loudly.

## Step 2 — interpret

Report as a compact table:

| Metric | Value | Meaning |
|---|---|---|
| Hit@5 | **0.92** | 9 of 10 queries find the right doc in the top 5 results |
| MRR | **0.79** | On average the right doc ranks ~1.3 in the list (1 / 0.79) |
| nDCG@10 | **0.87** | Ranking quality — 1.0 is perfect, random baseline is ~0.15 |
| Precision@5 | **0.67** | Of the top 5 results, 67% are relevant |

**Interpretation thresholds** (rough heuristics, corpus-dependent):

- **Hit@5 ≥ 0.85** → healthy. Users rarely need to read past position 5.
- **Hit@5 0.70-0.85** → acceptable. Keyword-saturated corpus likely; little room to grow without changing the eval set.
- **Hit@5 < 0.70** → probably a corpus or chunking problem. Run `/gnosis:tune` to sweep chunk sizes.
- **MRR / Hit@5 ratio < 0.80** → relevant docs exist in top-5 but ranked too low. Try title-prepending or reranking (`/gnosis:tune` covers both experiments).
- **nDCG@10 ≥ 0.85 and Hit@5 = 0.92** matches our published dev-docs baseline — you're in the same regime as gnosis-mcp's own corpus.

## Step 3 — compare to baseline (mode: default, diff, save)

Baseline lives at `~/.local/share/gnosis-mcp/eval-baseline.json`.

**If baseline exists** (default + diff modes):

```
Metric       Now       Last (2026-04-18)   Δ
Hit@5        0.9200    0.9200              —
MRR          0.7933    0.7933              —
nDCG@10      0.8702    0.8702              —
P@5          0.6680    0.6680              —
```

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

Based on the numbers, point at the next action:

| State | Next action |
|---|---|
| Everything green, no regression | "Numbers look healthy. Run `/gnosis:ingest <path> --prune` after any doc change to keep them that way." |
| Hit@5 dropped > 2 points | "Regression. Run `/gnosis:status diag` to rule out corruption, then `git diff` any recent ingest or config changes." |
| Hit@5 healthy but MRR weak | "Ranking is the weak link. `/gnosis:tune` can test title-prepending — sometimes worth +3 MRR points on keyword-saturated corpora." |
| Hit@5 < 0.70 | "Chunk size or corpus shape issue. `/gnosis:tune` will sweep chunk sizes 1000-4000 and report the optimum — ~10 min runtime." |
| No regression but first time | "Run `/gnosis:eval save` to lock these as your baseline. Future runs will diff against this." |

---

## When to skip `/gnosis:eval`

- **BEIR-style public benchmark** → use `tests/bench/bench_beir.py` instead. That's external validity; eval is in-distribution validity.
- **End-to-end MCP round-trip timing** → `tests/bench/bench_mcp_e2e.py`.
- **Comparison across embedders** → `scripts/bench-embedders.sh` for the full matrix.

## What the numbers mean for non-experts

See [`docs/how-we-measure-search.md`](../../docs/how-we-measure-search.md)
for a plain-English explainer of Hit@K / MRR / nDCG (if that doc
exists in this corpus; otherwise point at the gnosismcp.com version:
https://gnosismcp.com/docs/how-we-measure-search).
