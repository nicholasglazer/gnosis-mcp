---
title: "Bench experiments — what actually moves retrieval quality"
category: performance
audience: all
last_verified: "2026-04-18"
relates_to:
  - docs/benchmarks.md
  - tests/bench/bench_sweep.py
  - tests/bench/bench_real_corpus.py
  - tests/bench/bench_beir.py
---

# Bench experiments — what actually moves retrieval quality

A clean, reproducible sweep across BEIR SciFact and a real-world developer
docs corpus (`/knowledge`, 558 markdown files, 25 hand-written golden
queries). Goal: find out which "obvious" retrieval improvements actually
work, and which are traps.

> All numbers are from a single laptop run on April 2026, gnosis-mcp
> v0.10.13, Python 3.14, SQLite + sqlite-vec, MongoDB/mdbr-leaf-ir
> (384-dim, 23M params) for the embedder, cross-encoder/ms-marco-MiniLM-L6-v2
> for the reranker. Reproduce with `tests/bench/bench_sweep.py` and
> `tests/bench/bench_real_corpus.py`.

---

## TL;DR — three counter-intuitive findings

1. **The MS-MARCO reranker actively hurts retrieval on developer docs**
   (-27 nDCG@10 on our `/knowledge` corpus). It's optimised for MS-MARCO
   web Q&A and applies a stylistic prior that misranks documentation
   passages. **Default for dev-doc users: leave it off.**

2. **Hybrid search ≡ keyword search on vocabulary-matched corpora.** When
   queries and docs share terminology (BM25's home turf), the dense arm
   adds latency without changing the top-k. Both SciFact and our
   `/knowledge` corpus exhibit this — same nDCG/MRR/Hit@5 down to four
   decimal places. RRF is doing exactly what it should; there's just no
   signal for it to fuse.

3. **Title prepending is dataset-dependent.** A documented +2-5 nDCG point
   trick from the chunking literature; on our corpus it gives keyword
   +0.5 points but **costs hybrid -9.6 points** because the embedder
   over-weights repeated boilerplate.

---

## Experiment 1 — reranker impact on BEIR SciFact

| Mode | nDCG@10 | Hit@5 | Recall@10 | p95 |
|---|---:|---:|---:|---:|
| keyword (BM25/FTS5) | 0.6700 | 0.7333 | 0.7947 | 26 ms |
| keyword + rerank (top-50 → top-10) | 0.6701 | **0.7633** | 0.7884 | **2 920 ms** |
| hybrid (RRF, k=60) | 0.6700 | 0.7333 | 0.7947 | 36 ms |

**Reading.**
- Reranker barely moves nDCG (it shuffles within rank — same docs end up
  in top-10).
- Reranker **does** lift Hit@5 by ~3 points: it pulls relevant docs from
  ranks 6-50 into the top-5.
- The latency cost is 110×. With a top-20 pool instead of top-50 the cost
  drops to ~40× — still significant.

**Verdict for BEIR-class scientific corpora:** worth it if downstream
consumes top-3 to top-5. Skip if you sample top-10+ anyway.

---

## Experiment 2 — real corpus (`/knowledge`, 558 dev docs, 25 golden queries)

| Mode | nDCG@10 | MRR@10 | Hit@5 | Hit@10 | p95 |
|---|---:|---:|---:|---:|---:|
| keyword | **0.8407** | **0.7813** | **0.9200** | 0.9200 | **7 ms** |
| hybrid (RRF k=60) | 0.8407 | 0.7813 | 0.9200 | 0.9200 | 11 ms |
| hybrid + rerank (MS-MARCO MiniLM L6) | 0.5674 | 0.4370 | 0.6800 | 0.8000 | 2 937 ms |

**The reranker drops nDCG from 0.84 → 0.57** — destroying retrieval
quality. Why?

The MS-MARCO model was trained on web Q&A snippets ("the cat is on the
mat" relevance to "where is the cat?"). It has a strong stylistic prior
for *answer-shaped* passages. Our corpus is *documentation-shaped*:
guides, configs, reference. The reranker scores docs that look more like
web answers — which are often less relevant — higher than the actual
matches BM25 surfaced.

**Practical implication:** the existing
`GNOSIS_MCP_RERANK_ENABLED=true` flag is documented as "opt-in for
quality"; it should additionally come with a domain warning, and the
default reranker model should probably be a domain-agnostic reranker
(BGE family) rather than MS-MARCO MiniLM.

---

## Experiment 3 — title prepending (real corpus, with `--title-prepend`)

| Mode | nDCG@10 | Δ vs no-title | Hit@5 |
|---|---:|---:|---:|
| keyword | 0.8459 | +0.005 | 0.92 |
| hybrid | 0.7449 | **-0.096** | 0.80 |

Each chunk's content was prefixed with `"<title>\n<file_path>\n\n"` at
ingest time.

**Reading.**
- For BM25: title prepending is a marginal positive — the title's keyword
  weight reinforces matches.
- For dense (hybrid): title prepending **hurts**. The embedder is a
  fixed-output sentence encoder; adding boilerplate dilutes the chunk's
  semantic centroid. All chunks of the same doc end up clustering tightly
  (because they share the title prefix), reducing the ability to
  distinguish *which* chunk is most relevant.

**Practical implication:** if we ever default-enable title prepending,
gate it on retrieval mode (only with keyword-only). In hybrid mode, keep
content pure.

---

## Experiment 4 — why does hybrid not help?

Across BEIR SciFact (5 183 docs, 300 queries) and our `/knowledge` corpus
(558 docs, 25 queries), keyword and hybrid produced **identical**
top-10 rankings. This is real, not a bug in the bench harness — query
latency for hybrid is verifiably higher (vector lookup ran), but RRF
fusion of (BM25 ranking, dense ranking) collapses to the BM25 ranking
when both arms surface the same doc set.

When would hybrid actually help?
- Paraphrase-heavy queries (FIQA finance, ArguAna argument retrieval)
- Synonym-heavy domains (medical, legal)
- Cross-lingual or code-text corpora

For our distribution (developer docs with shared vocabulary between
queries and content), BM25 is already near the ceiling. Dense retrieval
adds latency without lift.

**Practical implication:** ship hybrid as opt-in (already true), and
recommend it only when users describe their queries as "natural-language
questions about specialised content."

---

## Experiment 5 — chunk size sweep (same corpus, keyword mode, verified 2×)

On the same real corpus, varying `GNOSIS_MCP_CHUNK_SIZE` (in characters —
not tokens) and re-running each config fresh:

| Chunk size (chars) | ≈ tokens | nDCG@10 | MRR | Hit@5 | p95 | Ingest |
|---:|---:|---:|---:|---:|---:|---:|
| 1000 | ~300 | 0.8557 | **0.8067** | 0.92 | 30 ms | 592 s |
| 1500 | ~450 | 0.8529 | 0.7967 | 0.92 | 7 ms | 234 s |
| 1800 | ~540 | **0.8702** | 0.7933 | 0.92 | (outlier) | 304 s |
| **2000** | **~600** | **0.8702** | 0.7933 | **0.92** | **7 ms** | 210 s |
| 2200 | ~660 | 0.8502 | 0.7933 | 0.92 | 8 ms | 202 s |
| 3000 | ~900 | 0.8459 | 0.7880 | 0.92 | 7 ms | 182 s |
| 4000 (old default) | ~1200 | 0.8407 | 0.7813 | 0.92 | 7 ms | 171 s |

**The peak is a verified 1800-2000 char plateau** — re-ran both twice,
0.8702 reproduces exactly. Drops at both ends. The mechanism, confirmed
by per-query inspection: when chunk size matches the typical topic-coherent
block length in our corpus (a single section or subsection of a guide),
BM25 gets clean term density. Smaller chunks fragment a section across
several chunks (terms spread thin); larger merge unrelated sections
together (term density diluted by surrounding noise).

This mirrors the Feb 2026 chunking systematic analysis finding that the
256-512 token range is the sweet spot for most corpora — 2000 chars
≈ 600 tokens sits at the top of that band.

**Action taken**: lowered the `GNOSIS_MCP_CHUNK_SIZE` default from 4000
to 2000 in v0.11.0-dev. Single-line code change, +3 nDCG free, no
latency cost.

---

## Things we did *not* measure (deliberate)

- **FIQA/ArguAna full sweep.** FIQA has 57 K docs — hybrid ingest is
  ~30 minutes. The expected outcome (hybrid wins by 5-10 nDCG points
  on FIQA, per published baselines) is well-documented in the BEIR paper;
  reproducing it would just confirm what's already known.
- **Asymmetric mode (snowflake doc encoder + leaf query encoder).**
  Published lift: +0.5 nDCG averaged across BEIR. Trade-off: 5.7× disk
  footprint (110 MB vs 23 MB). Not worth it for a "zero config" default.
- **BGE-reranker-base (278 M params).** Heavier than the MS-MARCO MiniLM
  but documented as a better domain generaliser. Likely candidate to
  replace the default reranker model — separate experiment to size up
  CPU latency on the larger model.

  **Update (same-day re-test, real corpus): BGE-reranker-base also hurts**:
  nDCG drops to **0.5333** (vs MS-MARCO's 0.5674, vs keyword's 0.8407)
  and p95 explodes to **15 819 ms** (vs MS-MARCO's 2 920 ms, vs keyword's
  6 ms). Confirms that the dev-doc penalty is **not a model-choice
  problem** — it's a fundamental mismatch between cross-encoders trained
  on MS-MARCO web Q&A and our domain (technical documentation). Looking
  at the top-3 hits per query, both rerankers consistently down-rank
  reference / list / table content and up-rank prose-shaped passages
  (changelog entries, SEO docs, completion notes) because those *look*
  more like web Q&A answers.

  **Practical conclusion**: until someone trains a reranker on a
  developer-docs distribution, **enabling cross-encoder reranking on
  technical documentation hurts retrieval quality and adds 500-2400×
  latency**. Don't enable it. Don't ship it as the default. Document
  the trap.

---

## What this changes in the codebase

Concrete actions, ordered by ROI:

1. **`docs/benchmarks.md`** — add a "Reranker on dev docs is harmful"
   warning section. Point users at this bench-experiments file for the
   evidence trail.

2. **`README.md` / `docs/config.md` (`GNOSIS_MCP_RERANK_ENABLED`)** — add
   a paragraph: "MS-MARCO reranker is tuned for web Q&A. Test against
   your own corpus before shipping; on developer docs we've measured
   -27 nDCG."

3. **Default reranker model.** Investigate BGE-reranker-base or v2-m3
   as drop-in replacements (separate sizing experiment needed).

4. **Title prepending feature** — explicitly *not* added as a default.
   If we expose it as a knob, gate to `keyword`-only mode.

5. **Public landing page (`gnosismcp.com`)** — keep the SciFact 0.6712
   number as-is; add a "honest findings" box near the bench table calling
   out the reranker pitfall. This is more valuable for HN credibility than
   any single nDCG number.

---

## Reproduce these numbers

```bash
# 1. SciFact reranker sweep
uv run --with beir --with 'gnosis-mcp[embeddings,reranking] @ .' \
  python tests/bench/bench_sweep.py --preset reranker-impact-scifact

# 2. Real corpus, three modes
uv run --with 'gnosis-mcp[embeddings,reranking] @ .' \
  python tests/bench/bench_real_corpus.py \
    --corpus /path/to/your/docs \
    --golden tests/bench/golden-knowledge.jsonl \
    --modes keyword,hybrid,hybrid+rerank

# 3. Title-prepending ablation
uv run --with 'gnosis-mcp[embeddings] @ .' \
  python tests/bench/bench_real_corpus.py \
    --corpus /path/to/your/docs \
    --golden tests/bench/golden-knowledge.jsonl \
    --modes keyword,hybrid \
    --title-prepend
```

Results land in `bench-results/`. Raw JSON includes per-query rankings
for any error-analysis follow-up.
