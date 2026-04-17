"""RAG-oriented benchmarks: retrieval quality + hybrid-vs-keyword comparison.

Unlike bench_search.py (speed only), this reports the metrics that matter for
a documentation server feeding an AI agent:
  - Precision@K
  - Hit Rate@K
  - Mean Reciprocal Rank (MRR)

Runs each eval case in two modes:
  1. Keyword-only (FTS5 / tsvector BM25)
  2. Hybrid (keyword + local ONNX embedding, RRF fusion)

Usage:
    uv run python tests/bench/bench_rag.py
    uv run python tests/bench/bench_rag.py --json

Requires the [embeddings] extra for hybrid mode.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Make the eval harness importable as a library
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from eval.test_search_quality import (  # type: ignore  # noqa: E402
    K,
    SAMPLE_DOCS,
    SAMPLE_GIT_HISTORY_DOCS,
    _load_cases,
    _score_query,
    EvalSummary,
)
from gnosis_mcp.config import GnosisMcpConfig  # noqa: E402
from gnosis_mcp.ingest import chunk_by_headings  # noqa: E402
from gnosis_mcp.sqlite_backend import SqliteBackend  # noqa: E402


async def _build_db(tmp_db: Path, *, with_embeddings: bool) -> SqliteBackend:
    cfg = GnosisMcpConfig(
        database_url=str(tmp_db),
        backend="sqlite",
        embed_provider="local" if with_embeddings else None,
    )
    backend = SqliteBackend(cfg)
    await backend.startup()
    await backend.init_schema()

    if with_embeddings:
        from gnosis_mcp.local_embed import get_embedder

        embedder = get_embedder()
    else:
        embedder = None

    for doc in SAMPLE_DOCS + SAMPLE_GIT_HISTORY_DOCS:
        chunks = chunk_by_headings(doc["content"], doc["path"], max_chunk_size=4000)
        texts = [c["content"] for c in chunks]
        embeddings = embedder.embed(texts) if embedder else None
        await backend.upsert_doc(
            doc["path"],
            texts,
            title=doc["title"],
            category=doc["category"],
            embeddings=embeddings,
        )

    return backend


async def _evaluate(backend: SqliteBackend, mode: str) -> tuple[EvalSummary, float, float]:
    cases = _load_cases()
    summary = EvalSummary()

    embedder = None
    if mode == "hybrid":
        from gnosis_mcp.local_embed import get_embedder

        embedder = get_embedder()

    latencies: list[float] = []
    embed_latencies: list[float] = []

    for case in cases:
        query_embedding = None
        if embedder is not None:
            t = time.perf_counter()
            query_embedding = embedder.embed([case["query"]])[0]
            embed_latencies.append(time.perf_counter() - t)
        t = time.perf_counter()
        results = await backend.search(
            case["query"],
            category=case.get("category"),
            limit=K,
            query_embedding=query_embedding,
        )
        latencies.append(time.perf_counter() - t)
        returned = [r["file_path"] for r in results]
        summary.results.append(
            _score_query(
                query=case["query"],
                expected_paths=case["expected_paths"],
                returned_paths=returned,
                description=case.get("description", ""),
            )
        )

    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    return summary, p50, p95


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(len(s) * p / 100))
    return s[idx] * 1000  # ms


async def _run(use_json: bool) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bench_rag.db"

        backend = await _build_db(db_path, with_embeddings=False)
        kw_summary, kw_p50, kw_p95 = await _evaluate(backend, mode="keyword")
        await backend.shutdown()

        db_path.unlink()
        backend = await _build_db(db_path, with_embeddings=True)
        hy_summary, hy_p50, hy_p95 = await _evaluate(backend, mode="hybrid")
        await backend.shutdown()

    results = {
        "cases": len(kw_summary.results),
        "keyword": {
            "hit_rate": kw_summary.hit_rate,
            "mrr": kw_summary.mrr,
            "mean_precision_at_k": kw_summary.mean_precision,
            "latency_p50_ms": round(kw_p50, 3),
            "latency_p95_ms": round(kw_p95, 3),
        },
        "hybrid": {
            "hit_rate": hy_summary.hit_rate,
            "mrr": hy_summary.mrr,
            "mean_precision_at_k": hy_summary.mean_precision,
            "latency_p50_ms": round(hy_p50, 3),
            "latency_p95_ms": round(hy_p95, 3),
        },
    }

    if use_json:
        print(json.dumps(results, indent=2))
        return

    print(f"\nRAG Quality Benchmark — {results['cases']} cases, K={K}")
    print("=" * 64)
    print(f"{'Mode':<10} {'Hit@K':>8} {'MRR':>8} {'P@K':>8} {'p50ms':>10} {'p95ms':>10}")
    print("-" * 64)
    for mode in ("keyword", "hybrid"):
        m = results[mode]
        print(
            f"{mode:<10} "
            f"{m['hit_rate']:>8.3f} "
            f"{m['mrr']:>8.3f} "
            f"{m['mean_precision_at_k']:>8.3f} "
            f"{m['latency_p50_ms']:>10.3f} "
            f"{m['latency_p95_ms']:>10.3f}"
        )
    print("=" * 64)


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG-oriented retrieval benchmark")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()
    asyncio.run(_run(args.json))


if __name__ == "__main__":
    main()
