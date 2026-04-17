---
title: Benchmarks
category: performance
audience: all
last_verified: "2026-04-17"
relates_to:
  - tests/bench/bench_search.py
  - tests/bench/bench_rag.py
  - tests/bench/bench_mcp_e2e.py
  - tests/eval/test_search_quality.py
---

# Benchmarks

Captured on gnosis-mcp v0.10.13, Python 3.14, Linux x86_64 laptop CPU.

Three distinct benchmark suites — each answers a different question.

## TL;DR

| Question | Answer |
|----------|--------|
| How fast is search? | **9,463 QPS, 0.16 ms p95** on 100 docs; **839 QPS, 3.0 ms p95** on 5 000 docs (SQLite keyword) |
| Is retrieval accurate? | **Hit Rate@5 = 1.00, MRR = 0.95, P@5 = 0.67** on 10 eval cases |
| Does hybrid search help? | No lift on this corpus (already saturated). Hybrid p95 ≈ 2× keyword due to embedding cost |
| What does an agent pay per tool call? | **~8.7 ms mean, 13.0 ms p95** end-to-end through the MCP stdio protocol |
| How fast is ingest? | **~18–21 K chunks/s** across corpus sizes; re-ingest skipped via content hashing |

---

## 1. Search speed — SQLite FTS5 (scale curve)

Synthetic corpus, 1 000 queries each, median of 3 runs, in-memory DB.

| Docs | Chunks | Ingest (s) | QPS | p50 (ms) | p95 (ms) | p99 (ms) | Hit rate |
|-----:|-------:|-----------:|-----:|---------:|---------:|---------:|---------:|
| 100 | 300 | 0.015 | 9 463 | 0.10 | 0.16 | 0.19 | 1.00 |
| 500 | 1 500 | 0.088 | 3 945 | 0.22 | 0.44 | 0.48 | 1.00 |
| 1 000 | 3 000 | 0.179 | 2 768 | 0.29 | 0.72 | 0.78 | 1.00 |
| 2 000 | 6 000 | 0.319 | 1 889 | 0.38 | 1.23 | 1.32 | 1.00 |
| 5 000 | 15 000 | 0.844 | 839 | 0.80 | 2.97 | 3.54 | 1.00 |
| 10 000 | 30 000 | 1.642 | 471 | 1.38 | 5.60 | 6.29 | 1.00 |

Sub-millisecond p95 through 2 000 docs. Still sub-10 ms at 10 000 docs — well under the 1-second budget an LLM agent can tolerate per tool call.

**Reproduce:**
```bash
uv run python tests/bench/bench_search.py --docs 1000 --queries 1000 --json
```

---

## 2. Retrieval quality — RAG-native metrics

Ten hand-authored query→expected-path cases (internal guides + git-history docs).

| Mode | Hit Rate@5 | MRR | Mean Precision@5 | p50 ms | p95 ms |
|------|-----------:|----:|----------------:|-------:|-------:|
| Keyword (FTS5 + BM25) | 1.000 | 0.950 | 0.668 | 0.12 | 0.27 |
| Hybrid (FTS5 + ONNX embeddings, RRF) | 1.000 | 0.950 | 0.668 | 0.24 | 0.41 |

**Takeaways**
- On a small corpus with distinctive keywords, keyword search already saturates — hybrid adds no lift but ~2× latency (embedding cost).
- The real payoff for hybrid appears on larger corpora with less distinctive query vocabulary (paraphrase, synonym) — not present in this test set.
- MRR = 0.95 means the first relevant document is almost always #1 in the result list.
- Precision@5 = 0.67 reflects the fact that several relevant docs exist for a given query — we return multiple correct matches in the top 5.

**Reproduce:**
```bash
uv run python tests/bench/bench_rag.py              # formatted table
uv run python tests/bench/bench_rag.py --json       # machine-readable
```

---

## 3. End-to-end MCP protocol latency

What a real MCP client (Claude Code, Cursor, Windsurf) pays per tool call —
subprocess stdio transport, full JSON-RPC round trip.

| Operation | Mean | p50 | p95 | p99 |
|-----------|-----:|----:|----:|----:|
| `initialize` (one-time handshake) | 407 ms | — | — | — |
| `list_tools` | — | 2.2 ms | — | — |
| `search_docs` (100 iterations) | **8.7 ms** | 8.1 ms | 13.0 ms | 15.8 ms |

Compare to the in-process search bench (0.16 ms p95) — the **MCP protocol overhead
is ~8 ms**: JSON-RPC marshalling, stdio pipe, FastMCP dispatch, serialisation of
results. This is what dominates real-world agent latency, not the search itself.
The v0.10.13 jump from ~13 ms to ~8.7 ms came from upgrading the `mcp` SDK to
1.27 and the transport improvements that shipped with it.

**Reproduce:**
```bash
uv run python tests/bench/bench_mcp_e2e.py --queries 100
```

---

## 4. Ingest throughput

| Corpus | Chunks | Time (s) | Throughput |
|--------|-------:|---------:|----------:|
| 100 docs | 300 | 0.014 | ~21 000 chunks/s |
| 1 000 docs | 3 000 | 0.146 | ~20 500 chunks/s |
| 5 000 docs | 15 000 | 0.792 | ~18 900 chunks/s |
| 10 000 docs | 30 000 | 1.680 | ~17 900 chunks/s |

Roughly linear. Re-ingestion of unchanged files is skipped via SHA-256 content
hashing (near-zero cost) — so a watcher re-running after every save only pays
for files that actually changed.

---

## 5. PostgreSQL (pgvector)

PostgreSQL numbers are captured manually — no CI service container yet (PG CI
is opt-in via `GNOSIS_MCP_CI_PG`). To reproduce:

```bash
docker run -d --rm --name gnosis-bench-pg -p 15432:5432 \
  -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=gnosis_bench \
  pgvector/pgvector:pg15
sleep 3
PGPASSWORD=pw psql -h localhost -p 15432 -U postgres -d gnosis_bench \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

GNOSIS_MCP_DATABASE_URL="postgresql://postgres:pw@localhost:15432/gnosis_bench" \
  uv run gnosis-mcp init-db

# Then adapt bench_search.py or point your own workload at it.

docker stop gnosis-bench-pg
```

Expected ranges on the same laptop with network overhead dominating:

- 100 docs: ~3 500–4 000 QPS, p95 ~1–2 ms
- 1 000 docs: ~1 500–2 000 QPS, p95 ~3–5 ms
- 10 000 docs: ~600–900 QPS, p95 ~8–15 ms (HNSW index dominates)

PostgreSQL pulls ahead of SQLite once the corpus crosses ~50 000 chunks and
hybrid search is active — HNSW scales sub-linearly while sqlite-vec performs a
full scan.

---

## Regression gates

CI runs the bench suite nightly against the SQLite backend. A >10% regression
in any of the following blocks a release:

- QPS on 100- and 1 000-doc corpora
- p95 latency on the scale curve
- Hit Rate@5 on the eval cases
- Ingest throughput

## Methodology notes

- Each bench runs once per release and the median of ≥3 runs is recorded.
- Synthetic corpora are deterministic — seeded generators, repeatable.
- Eval cases are human-authored and cover guides, architecture docs, and git-history paths.
- Benchmarks run on laptop CPU — datacentre numbers will be higher but the shape is stable.
- These are ceilings, not guarantees. Production sees extra cost from concurrent
  clients, larger chunks, and network transport for HTTP or PostgreSQL.
