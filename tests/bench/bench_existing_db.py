"""Benchmark retrieval quality on an already-populated gnosis-mcp DB.

Unlike bench_real_corpus.py (which re-ingests a markdown directory into a
temp DB), this queries whatever corpus is already in the DB named by
GNOSIS_MCP_DATABASE_URL — e.g. a set of sites you ingested via `crawl`.

Usage:
  GNOSIS_MCP_DATABASE_URL=sqlite:///tmp/laptop-bench/corpus.db \
    uv run python tests/bench/bench_existing_db.py \
      --golden tests/bench/golden-laptop.jsonl \
      --label laptop-mdbr-crawled

Scoring matches bench_real_corpus: substring match of expected_paths against
file_path in top-k hits, computing Hit@5, Hit@10, MRR, nDCG@10.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Reuse the scoring + run_mode from bench_real_corpus
sys.path.insert(0, str(Path(__file__).parent))
from bench_real_corpus import GoldenCase, run_mode


async def main_async(args) -> int:
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.local_embed import LocalEmbedder
    from gnosis_mcp.rerank import get_reranker

    cases: list[GoldenCase] = []
    with open(args.golden) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            cases.append(
                GoldenCase(
                    query=obj["query"],
                    expected_paths=obj["expected_paths"],
                    description=obj.get("description", ""),
                )
            )
    print(f"  loaded {len(cases)} golden cases")

    cfg = GnosisMcpConfig.from_env()
    cfg = GnosisMcpConfig(
        database_url=cfg.database_url,
        backend=cfg.backend,
        writable=True,
        embedding_dim=args.embed_dim,
        embed_dim=args.embed_dim,
        rrf_k=args.rrf_k,
    )
    backend = create_backend(cfg)
    await backend.startup()

    try:
        stats = await backend.get_stats()
        doc_count = stats.get("documents", stats.get("docs", 0))
    except Exception:
        doc_count = -1
    print(f"  DB: {cfg.database_url}  docs={doc_count}")

    print(f"  embedder: {args.embed_model} @ dim={args.embed_dim}")
    embedder = LocalEmbedder(model_id=args.embed_model, dim=args.embed_dim)
    reranker = get_reranker(model=args.rerank_model)

    results = []
    for mode in args.modes.split(","):
        mode = mode.strip()
        r = await run_mode(
            backend, embedder, reranker, cases, mode=mode, k=args.k, rerank_n=args.rerank_n
        )
        print(
            f"  {mode:18s}  nDCG={r['ndcg_at_10']:.4f}  MRR={r['mrr']:.4f}  "
            f"Hit@5={r['hit_at_5']:.4f}  Hit@10={r['hit_at_10']:.4f}  "
            f"p50={r['p50_ms']}ms  p95={r['p95_ms']}ms"
        )
        results.append(r)

    await backend.shutdown()

    out = {
        "label": args.label,
        "database_url": cfg.database_url,
        "embed_model": args.embed_model,
        "embed_dim": args.embed_dim,
        "docs": doc_count,
        "golden_cases": len(cases),
        "results": results,
    }
    out_path = (
        Path(args.out)
        if args.out
        else Path("bench-results") / f"{args.label or 'existing-db'}-{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"  → {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--golden", required=True)
    ap.add_argument(
        "--modes",
        default="keyword,hybrid,hybrid+rerank",
    )
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--rerank-n", type=int, default=50)
    ap.add_argument(
        "--rerank-model",
        default="cross-encoder/ms-marco-MiniLM-L6-v2",
    )
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument("--embed-model", default="MongoDB/mdbr-leaf-ir")
    ap.add_argument("--embed-dim", type=int, default=384)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
