---
title: "How we measure search quality (and where gnosis-mcp lands)"
category: docs
audience: all
last_verified: "2026-04-18"
relates_to:
  - docs/benchmarks.md
  - docs/bench-experiments-2026-04-18.md
  - docs/overview.md
---

# How we measure search quality

A plain-English guide to the numbers in our benchmarks. No prior IR
background assumed.

If you've ever stared at a table full of `nDCG@10`, `MRR`, `Hit@5` and
wondered which one to actually care about — this is for you.

---

## The librarian thought experiment

Forget search engines for a minute. Imagine a really good librarian.

You walk up and say: *"I'm setting up Stripe webhooks for a Shopify
store — where do I start?"*

A great librarian doesn't read your mind. She has shelves of books, no
time to read them all, and a few minutes to put 5–10 of the most
relevant ones in your hands. The question is: how good was her stack?

Every search-quality metric is a different way of grading her stack.
Once you have the picture, the rest of the page is easy.

---

## The four numbers worth knowing

### Hit@5 — *"Did she put the right book in the top five?"*

The simplest metric. For each of your questions, look at the first 5
results. Did at least one *useful* one show up?

If you ask 100 questions and 92 of them have a useful book in the top 5,
**Hit@5 = 0.92**.

That's literally it. This is the metric that tracks how often a real
user finds what they're looking for, because most people don't scroll
past the first handful.

| Hit@5 | What it feels like |
|---|---|
| 0.50 | Half the time you're frustrated and rephrasing the query |
| 0.70 | Decent — most queries land |
| 0.85 | Good — you stop noticing search exists |
| 0.92+ | You can rely on it without thinking |

**On our own docs corpus, gnosis-mcp scores 0.92.** The librarian gets
the right book in your hands 23 times out of 25.

---

### MRR — *"How high up on the stack was the right book?"*

Hit@5 is binary: did it work or not. MRR is "yeah, but how high?"

If the right answer is the first book on the stack, that's a 1.0 — perfect.
If you had to pick up the second book to find it, that's a 0.5. Third
book, 0.33. Fifth book, 0.20. Bury it past book ten, you score zero.

Average across all your questions and you get the **MRR**.

| MRR | Average position of the first hit |
|---|---|
| 1.0 | Always #1 |
| 0.7 | Usually 1 or 2 |
| 0.5 | Usually around 2 |
| 0.3 | Usually around 3-4 |

**Our MRR on real dev docs is 0.81** (after v0.11's chunk-size tune —
it was 0.78 before). The right answer is the first result you click,
most of the time.

---

### nDCG@10 — *"Was the whole stack in a sensible order?"*

The most informative metric, and the one IR researchers obsess over.

Hit@5 doesn't care about order. MRR only cares about the first hit.
nDCG@10 grades the **whole top-10**, with relevant books at the top
worth more than relevant books at the bottom.

Range: 0.0 to 1.0. A 1.0 means *the perfect ordering* — every relevant
book exactly in the right slot. Real systems live in 0.5–0.85.

| nDCG@10 | Verdict |
|---|---|
| 0.40 | The library is a mess but you'll find it eventually |
| 0.55 | Search basically works |
| 0.70 | Good — what most well-built systems hit |
| 0.85+ | Very good — the librarian *knows* the collection |

**Our keyword search hits 0.87 on real dev docs** (v0.11, with
`GNOSIS_MCP_CHUNK_SIZE=2000`). That's firmly in "very good" territory
without doing anything fancy.

---

### p95 latency — *"How long until the slow 5% finish?"*

Switching gears: this is about speed, not quality.

If you run a thousand queries and sort them by how long they took, p95
is the 950th one — the *unlucky* tail. Median (p50) is what your average
query feels like. p95 is what the slow ones feel like.

Why the unlucky tail? Because every modern app reads from a search
index in the inner loop. If 5% of queries take 3 seconds instead of
30 milliseconds, that's the user experience that ends up in support
tickets.

| p95 | Feels like |
|---|---|
| < 50 ms | Instant — you can search on every keystroke |
| 50 – 200 ms | Snappy |
| 200 ms – 1 s | Noticeable wait |
| 1 s+ | Visible delay, breaks flow |

**gnosis-mcp's p95 on a 558-doc corpus is 7 ms.** Practically free.
Adding a cross-encoder reranker pushes it to 2 900 ms — which is why
the reranker is *off* by default.

---

## So how good is "good"? Industry context

The standard yardstick is **BEIR** — 18 datasets covering science,
finance, arguments, medical literature, biographies, forums. Run the
same queries on each, average the nDCG@10. That single number tells you
how *generally* capable a retriever is.

Here's where the major players land in April 2026:

| System | BEIR average nDCG@10 | Notes |
|---|---:|---|
| BM25 (the keyword baseline) | 0.43 | Free, fast, the floor for 30 years |
| **gnosis-mcp default embedder (mdbr-leaf-ir, 23 M params)** | **~0.54** | **#1 in the ≤100 M class on the public leaderboard** |
| BGE-Large-EN (335 M) | 0.52 | 14× heavier, lower score |
| OpenAI text-embedding-3-large | 0.55 | Cloud only, paid per query |
| Cohere Embed v4 | 0.54 | Cloud only, paid per query |
| Voyage-Large-2 (top of leaderboard) | 0.55 | Cloud only, paid per query |

We ship the **best free, local, small-model embedder available in 2026**.
Nothing in the same size class beats it. You match commercial cloud
models on quality without sending your docs to a cloud API.

---

## What this looks like on a real dataset

**SciFact** — a public benchmark for retrieving scientific evidence
(5 183 papers, 300 questions). Every retrieval system on Earth has
been measured on this thing.

| System | nDCG@10 |
|---|---:|
| Random | ~0.10 |
| BM25 (canonical Lucene baseline) | 0.679 |
| **gnosis-mcp (keyword only)** | **0.671** |
| ColBERTv2 (much heavier model) | 0.693 |
| Dense + cross-encoder rerank | 0.745 |
| Specialised biomedical models | 0.78+ |

Our keyword path is **within 1% of the canonical BM25 baseline** —
the 30-year-old gold standard for general-purpose retrieval. To beat it
on a domain like biomedical literature, you'd need a model fine-tuned
specifically on biomedical text. That's an explicit choice we don't
make: gnosis-mcp is meant to be useful for *your* docs, whatever they
are, with zero configuration.

---

## On your own corpus, the numbers go up

The real question isn't "what does gnosis-mcp score on someone else's
dataset?" — it's "how does it do on *yours*?"

We dogfooded on our own `/knowledge` corpus: 558 markdown files
(architecture docs, integration guides, runbooks), 25 hand-written
real-developer questions ("how do I deploy safely?", "how does the
affiliate system work?", "where's the meta API reference?").

v0.11 numbers (after the chunk-size tune):

| Metric | Score | Where this lands | Δ vs v0.10 |
|---|---:|---|---:|
| Hit@5 | **0.92** | The right doc is in the top 5 for 23 / 25 questions | — |
| nDCG@10 | **0.87** | Top of the "very good" tier | **+0.03** |
| MRR | **0.81** | The right doc is usually result #1 or #2 | **+0.03** |
| p95 | **7 ms** | Imperceptible | — |

The +3-point lift came from changing one env var: `GNOSIS_MCP_CHUNK_SIZE`
from 4000 to 2000 chars. See [bench-experiments-2026-04-18](bench-experiments-2026-04-18.md)
for the full chunk-size sweep and why 2000 is the peak.

When the corpus matches the queries — same words, same domain — BM25
keyword search dominates. Embeddings help when queries are paraphrased
("how do I cancel a customer's subscription" against docs that say
"unsubscribe a user") or when there's a lot of synonymy (medical, legal).

---

## Three honest gotchas we discovered

We were going to ship the cross-encoder reranker as a "quality knob".
Then we actually measured it. Here's what we found.

### 1. The reranker we ship hurts dev docs

The standard ms-marco-MiniLM-L6 reranker — used by basically every
RAG pipeline online — drops our nDCG from **0.84 to 0.57**. Hit@5
collapses from 0.92 to 0.68.

Why? It was trained on web Q&A snippets. It has a stylistic prior for
*answer-shaped* passages and downranks doc-shaped ones. When your
corpus is API references and runbooks, it picks the wrong things.

We don't enable it by default and we say so out loud. You should
test any reranker against your own corpus before turning it on.

### 2. Hybrid search is identical to keyword on most "your-own-docs" corpora

Hybrid (keyword + vector embedding fused via Reciprocal Rank Fusion)
is the *fashionable* approach. We support it, and on the right corpus
it shines. On both SciFact and our own dev docs, hybrid produced
**byte-identical** top-10 rankings to keyword alone — for an extra
4 ms of vector lookup latency.

When does hybrid actually help? Paraphrase-heavy domains: finance Q&A
(FIQA), argument retrieval (ArguAna), customer-support tickets where
users describe symptoms in their own words. If your queries use the
same words as your docs, BM25 already nails it.

### 3. "Prepend the title to each chunk" — a documented +5 nDCG trick — actually hurt our hybrid by 9.6 points

Lots of RAG guides say to prepend doc title and path to every chunk
before embedding it. Sounds reasonable. We tested it. Keyword
search gained a marginal +0.5 nDCG. Hybrid *lost* 9.6 nDCG —
because the embedder over-weighted the repeated boilerplate, making
all chunks of one doc look identical.

Lesson: every "obvious" RAG improvement should be measured against
your own corpus before shipping.

---

## What to do with all this

If you're picking a search tool for your AI agent:

1. **Measure on your own corpus.** Even a small golden set of 20-30
   queries you wrote by hand tells you more than any leaderboard. We
   ship a harness for this — see the
   [reproduce](#reproduce-it-yourself) section.

2. **Default-on means tested.** Anything with significant cost (a
   reranker, a larger embedder, a multi-stage pipeline) should justify
   itself on your numbers, not on a paper's.

3. **Latency budget matters.** A 50-point quality bump that costs
   3 seconds per query is rarely the right trade for an AI agent making
   tool calls in a loop.

4. **Honesty beats shiny numbers.** Anyone publishing benchmarks
   without listing a metric where they lose, or a config where their
   choice backfires, is selling you something. Ours are above. Now you
   know what we know.

---

## Reproduce it yourself

Two scripts ship with gnosis-mcp:

```bash
# 1. Public BEIR benchmark — same numbers anyone in IR can compare against
uv run --with beir --with 'gnosis-mcp[embeddings] @ .' \
  python tests/bench/bench_beir.py --dataset scifact

# 2. Your own corpus + your own golden queries
uv run --with 'gnosis-mcp[embeddings,reranking] @ .' \
  python tests/bench/bench_real_corpus.py \
    --corpus ./your-docs \
    --golden ./your-questions.jsonl \
    --modes keyword,hybrid,hybrid+rerank
```

The golden file is one JSON object per line:

```json
{"query": "how does our auth work", "expected_paths": ["docs/auth-guide", "architecture/auth"]}
```

Five minutes to write 20 questions, you've got numbers that mean
something for your team.
