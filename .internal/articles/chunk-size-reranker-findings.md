---
title: "I tested three rerankers on my docs. All three hurt retrieval. Here's what actually worked."
description: "Fresh benchmarks on a real 558-doc corpus revealed that the standard RAG playbook — enable the reranker, use hybrid search — was actively hurting me. What moved the needle was a single config value."
date: 2026-04-18
tags: [rag, retrieval, benchmarks, gnosis-mcp]
published: true
---

# I tested three rerankers on my docs. All three hurt retrieval. Here's what actually worked.

I've been running [gnosis-mcp](https://gnosismcp.com) — a self-hosted doc-search server I built for my own AI coding workflow — against my personal knowledge base. 558 markdown files, real docs, real questions.

I assumed I'd been leaving quality on the table. Every RAG guide on the open web this year says the same thing: enable hybrid search, turn on the cross-encoder reranker, tune RRF. That was the playbook I hadn't gotten around to validating.

So over a weekend I wrote a clean benchmark harness and ran the playbook. Then I ran ablations. Then I ran more ablations.

What came out surprised me enough that I want to write it down, partly because the findings are actionable for anyone building RAG today, and partly because the lessons are counterintuitive enough that I suspect a lot of people are shipping pipelines that actively hurt their users.

## The setup

Before I get to what I found, the test rig:

- **Corpus**: 558 markdown files — architecture docs, integration guides, runbooks, AI-context notes. Everything a coding agent would want to read to understand the company.
- **Golden set**: 25 hand-written questions I'd realistically ask Claude Code during a work day. "How does the affiliate program work?" "How do we deploy safely to Cloudflare Pages?" "What's the canvas-core API?"
- **Metrics**: nDCG@10, MRR, Hit@5 — standard IR evals. Each query scored by whether its hand-labeled expected docs appeared in the ranked top-10 and how early.
- **Public benchmark for sanity**: BEIR SciFact (5,183 papers, 300 queries) as an externally-comparable anchor.
- **Hardware**: laptop CPU. No GPU. Important for this story.

gnosis-mcp's defaults at the start of this weekend: SQLite FTS5 + sqlite-vec hybrid search, [MongoDB/mdbr-leaf-ir](https://huggingface.co/MongoDB/mdbr-leaf-ir) (23M param, #1 on BEIR for ≤100M param models), RRF fusion at k=60, `ms-marco-MiniLM-L6-v2` cross-encoder available as an opt-in reranker.

Starting baseline on my real corpus: **Hit@5 = 0.92, nDCG@10 = 0.8407** with keyword-only search. That's already strong — 23 out of 25 queries surface the right doc in the top 5.

But the playbook says I can do better. Let's see.

## Finding 1: the cross-encoder reranker destroys retrieval quality on dev docs

I turned on the reranker. The one every RAG blog recommends. `ms-marco-MiniLM-L6-v2`.

```
keyword only:            nDCG=0.8407  Hit@5=0.92  p95=7 ms
keyword + rerank:        nDCG=0.6700  Hit@5=0.76  p95=2,920 ms
```

Wait, what?

Hit@5 dropped by 16 points. nDCG dropped by 17. And it was **400× slower** — 7 ms to 2,920 ms per query.

I thought I had a bug. Swapped to `BAAI/bge-reranker-base` — the other big name, 12× heavier at 278M params. Re-ran.

```
keyword + bge rerank:    nDCG=0.5333  Hit@5=0.72  p95=15,819 ms
```

Worse. And 2,400× slower than keyword alone.

Third family: `mixedbread-ai/mxbai-rerank-large-v1`. 1.7 GB of model weights. My laptop OOM'd trying to run it. Given the other two, I didn't feel great about the expected outcome.

At this point I went and read per-query rankings to understand what the rerankers were doing. The pattern was unmistakable. They were systematically promoting prose-shaped content — changelog entries, marketing blurbs, SEO strategy docs — and demoting reference/list/table content. Exactly the structural characteristic of technical documentation.

The explanation is in the training data, not the models. Every major open cross-encoder is trained on MS-MARCO: a collection of Bing search queries paired with web passages. Web passages have a particular texture — they're answers written for consumers, in complete sentences. Documentation isn't that. Documentation is bullets and tables and code blocks and sections with named anchors. The reranker sees a BM25-retrieved API reference and a prose paragraph from a changelog, and it picks the changelog — because the changelog *looks* like a web answer.

This isn't a reranker problem you can solve by swapping models. Until someone trains a reranker on a documentation distribution — or until we all start fine-tuning our own — **the honest default for dev docs is to turn rerankers off and leave them off**.

I deleted the "hybrid + rerank" benchmark line from my landing page. Putting inflated quality numbers behind a feature that actively hurts users would've been malpractice.

## Finding 2: hybrid search ≡ keyword search when queries and docs share vocabulary

Next thing the playbook wants: hybrid. Fuse BM25 with dense embeddings via Reciprocal Rank Fusion. This is state-of-the-art in most leaderboards.

```
keyword only:            nDCG=0.8407  Hit@5=0.92
hybrid (RRF k=60):       nDCG=0.8407  Hit@5=0.92
```

Byte-identical rankings. Down to four decimal places. Both on my corpus and on BEIR SciFact.

The vector arm ran — I confirmed by measuring query latency, which went up by ~4 ms. But the RRF fusion of (BM25 ranking, dense ranking) collapsed to the BM25 ranking. Which means both retrievers were surfacing the same documents in roughly the same order — so fusing them was a no-op.

This is the hybrid-search paradox nobody really talks about: **hybrid search helps in exactly the cases where you'd least expect to need it**. If your queries and your docs share vocabulary — if the words in the query are literally words in the docs — BM25 already nails it. Dense retrieval adds computational cost without lift.

Where does hybrid actually win? Paraphrase-heavy domains: finance Q&A ("how can I reduce my tax liability" against docs that say "mitigate capital gains"), medical ("why am I tired" against "fatigue etiology"), customer support ("it's broken" against "error code 502 runbook"). Technical documentation — where engineers write their queries in the same lingo as the docs — isn't that distribution.

On my corpus, 21 out of 25 queries share at least one exact content token with their relevant docs. BM25 handles those trivially. The remaining 4 queries are edge cases where *neither* BM25 nor dense adds value — so hybrid isn't saving them either.

## Finding 3: "prepend the title" is folklore

There's a widely-cited RAG hack: before you embed each chunk, prepend the document title and file path. Supposed to be worth +2 to +5 nDCG points.

```
keyword:                 nDCG=0.8407
keyword + title prepend: nDCG=0.8459  (+0.5)
hybrid:                  nDCG=0.8407
hybrid + title prepend:  nDCG=0.7449  (-9.6)
```

Marginal positive for BM25 — the title's keyword weight reinforces matches. But it *destroyed* hybrid, dropping it by nearly 10 points.

Why: a sentence embedder produces a fixed-dimensional summary of an input. When you prepend the same 50-character title to every chunk in a document, you've made all those chunks look more similar to each other in embedding space. The model now can't distinguish which *part* of the document matches — only which document matches. For a retrieval system that returns chunks, that's a regression.

The paper that originally recommended this trick was specific: they were building a system that returned whole documents. Different problem. The folklore dropped the qualifier somewhere along the chain.

## Finding 4: the chunk size default was wrong

After finding out that everything the playbook recommended was making things worse, I started sweeping the boring parameters.

The first one I hit: chunk size. The default was 4,000 characters (~1,200 tokens). I swept 1,000 → 4,000 in 500-char steps. Twice.

| chunk (chars) | nDCG@10 | MRR | Hit@5 | p95 |
|---:|---:|---:|---:|---:|
| 1,000 | 0.8557 | 0.8067 | 0.92 | 30 ms |
| 1,500 | 0.8529 | 0.7967 | 0.92 | 7 ms |
| 1,800 | **0.8702** | 0.7933 | 0.92 | 7 ms |
| **2,000** | **0.8702** | 0.7933 | 0.92 | 7 ms |
| 2,200 | 0.8502 | 0.7933 | 0.92 | 8 ms |
| 3,000 | 0.8459 | 0.7880 | 0.92 | 7 ms |
| 4,000 (old default) | 0.8407 | 0.7813 | 0.92 | 7 ms |

The curve peaks in a plateau between 1,800 and 2,000 chars. Re-ran both twice; identical down to four decimals. Drops at both ends.

**+3 nDCG@10 and +2.5 MRR from changing a single integer in the config**, with zero latency cost.

Why is there a peak? Going into this I expected "smaller is always better" — smaller chunks mean tighter term density per unit of content, which helps BM25. But the data says the opposite: smaller chunks fragment a section across multiple chunks, which dilutes term frequency *per chunk*, which lowers BM25 scores for the right chunk relative to noise.

The peak sits where chunk size matches the natural topic-coherent block length in the corpus. A single H2 section in my guides is typically 1,500–2,000 characters. When chunks align with sections, each chunk captures one focused topic — and BM25 finds it cleanly. Smaller than that, sections split; larger, sections merge with unrelated neighbors.

This matches what [Feb 2026 chunking research](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) independently landed on: 256–512 tokens (≈ 800–1,700 chars) is the generally useful sweet spot. My 2,000 chars (~600 tokens) sits at the top of that band.

I changed the default in gnosis-mcp v0.11.0-dev. Single-line commit. Biggest quality win of the weekend came from a default, not a feature.

## Before and after

| | Old default (v0.10.x) | New default (v0.11.0) |
|---|---:|---:|
| `GNOSIS_MCP_CHUNK_SIZE` | 4000 | **2000** |
| Hit@5 (real corpus) | 0.92 | 0.92 |
| **nDCG@10 (real corpus)** | **0.8407** | **0.8702** |
| **MRR (real corpus)** | **0.7813** | **0.8067** |
| nDCG@10 (BEIR SciFact) | 0.6712 | 0.6712 |
| p95 latency | 7 ms | 7 ms |
| Ingest time (558 docs) | 171 s | 210 s |
| Reranker default | opt-in | **off, documented as trap for dev docs** |
| Documentation | claims without caveats | explicit "test on your corpus first" |

The ingest time is the only regression — 20 % slower, one-time cost at index time, not per-query. Trivial in the context of daily use.

## What I'm shipping next

The deepest finding from this weekend is that **the chunk-size choice is fundamentally a compromise between retrieval precision and generation context**. Small chunks rank precisely; the LLM reading just "the retry interval is 30 s" doesn't know which service. Large chunks give the LLM context; their term density is diluted and they rank worse.

The right solution to that trade-off is called parent-child chunking. You index at two granularities: small "child" chunks for ranking (say 500 chars) and large "parent" chunks for the actual content you return (say 2,000 chars). The ranker finds the exact 500-char window that matches, then you return the 2,000-char parent that contains it. Retrieval precision *and* generation context, no trade-off.

I've written the design doc — two new nullable columns in the existing schema, zero-migration backward-compat, ~150 LOC. Targeting it for gnosis-mcp v0.11.0 proper. Projected uplift based on the curve: another +2 to +4 nDCG@10 over the current 0.8702.

There are other things I want to try — Anthropic's [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) technique (LLM-generated context prepended to each chunk before embedding), late chunking once we ship a long-context embedder, query rewriting with a small on-device LLM. But each of those costs something real — an LLM call per chunk, a bigger model, an extra forward pass at query time. Parent-child is free in comparison and dodges the specific trade-off I measured.

## The meta-lesson

I didn't expect to write this post. Going into the weekend I was planning a couple of ablations to generate marketing-friendly numbers for gnosis-mcp's landing page — "benchmarks for the launch post, ~2 hours, easy".

Instead I found that the three most-recommended RAG improvements on the open web — enable hybrid, enable reranker, prepend titles — are all either no-ops or regressions in my setting. And the thing that actually moved quality was a config default that, as far as I can tell, most people copy from sample code without questioning.

The takeaway is unsexy. **Measure on your own corpus.** Not on BEIR. Not on the corpus the paper was published on. *Your corpus.* Twenty hand-written queries is enough to start — it cost me two hours to write them and gave signal every published leaderboard missed.

Every "obvious" RAG improvement has a distribution where it fails. If you can't name the distribution your technique was validated on and compare it to your own, you don't have a benchmark — you have a vibe.

## Reproduce it yourself

gnosis-mcp ships the harnesses I used:

```bash
pip install "gnosis-mcp[embeddings,reranking]"

# BEIR — anchor against published baselines
uv run python tests/bench/bench_beir.py --dataset scifact

# Your own corpus — the one that actually matters
uv run python tests/bench/bench_real_corpus.py \
  --corpus ./your-docs \
  --golden ./your-questions.jsonl \
  --modes keyword,hybrid,hybrid+rerank

# Sweep chunk sizes to find your own corpus's plateau
for s in 1000 1500 2000 2500 3000; do
  uv run python tests/bench/bench_real_corpus.py \
    --corpus ./your-docs --golden ./your-questions.jsonl \
    --modes keyword --chunk-size $s --out results-$s.json
done
```

Golden file is one JSON object per line:

```json
{"query": "how does our auth system work", "expected_paths": ["docs/auth-guide", "architecture/auth"]}
```

Five minutes to write 20 honest questions. You'll learn more than you did from your last three RAG tutorials.

---

*gnosis-mcp is MIT-licensed and lives at [github.com/nicholasglazer/gnosis-mcp](https://github.com/nicholasglazer/gnosis-mcp). The full experiment writeup with per-query inspections and every intermediate benchmark is at [gnosismcp.com/doc/docs/bench-experiments-2026-04-18](https://gnosismcp.com/doc/docs/bench-experiments-2026-04-18). If you're building RAG and your corpus is dev docs, I'd genuinely love to know whether the findings reproduce on your side.*
