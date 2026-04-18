"""BEIR benchmark harness — retrieval quality on a public dataset.

Runs gnosis-mcp against a chosen BEIR dataset (default: SciFact — 5 183
corpus docs, 300 dev queries) and reports the metrics the RAG/IR
communities actually care about: nDCG@10, MRR@10, Recall@10, Hit@5.

Why BEIR: it's the standard cross-domain retrieval benchmark (Thakur et al.
2021). Results here are directly comparable to numbers published by
dense / hybrid / learned-sparse retrievers.

Usage:
    pip install gnosis-mcp[embeddings] beir
    uv run python tests/bench/bench_beir.py --dataset scifact
    uv run python tests/bench/bench_beir.py --dataset scifact --mode keyword
    uv run python tests/bench/bench_beir.py --dataset scifact --json

The BEIR library downloads the dataset on first run (~30 MB for SciFact).

Datasets worth trying (fits on a laptop):
  - scifact       5 183 docs · 300 queries · scientific-fact retrieval
  - nfcorpus      3 633 docs · 323 queries · medical literature
  - fiqa         57 638 docs · 648 queries · finance QA
  - arguana       8 674 docs · 1 406 queries · argument retrieval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

from gnosis_mcp.backend import create_backend  # noqa: E402
from gnosis_mcp.config import GnosisMcpConfig  # noqa: E402


def _try_beir_import():
    try:
        from beir import util  # type: ignore
        from beir.datasets.data_loader import GenericDataLoader  # type: ignore
    except ImportError as e:
        print(
            "BEIR not installed. Run:  pip install beir",
            file=sys.stderr,
        )
        raise SystemExit(2) from e
    return util, GenericDataLoader


async def ingest_corpus(backend, corpus: dict[str, dict[str, str]], embed: bool) -> None:
    """Ingest every BEIR corpus doc as a single-chunk document."""
    from gnosis_mcp.local_embed import get_embedder  # noqa: E402

    embedder = get_embedder() if embed else None
    total = len(corpus)
    t0 = time.perf_counter()
    batch: list[tuple[str, str, str]] = []  # (docid, title, body)
    BATCH = 64

    async def flush():
        nonlocal batch
        if not batch:
            return
        chunks = [f"{t}\n\n{b}".strip() for (_id, t, b) in batch]
        vecs_list = embedder.embed(chunks) if embedder is not None else None
        for (docid, title, _body), chunk_text in zip(batch, chunks, strict=False):
            embs = [vecs_list.pop(0)] if vecs_list is not None else None  # type: ignore[union-attr]
            await backend.upsert_doc(
                path=docid,
                chunks=[chunk_text],
                title=title or docid,
                category="beir",
                embeddings=embs,
            )
        batch = []

    for i, (docid, doc) in enumerate(corpus.items()):
        batch.append((docid, doc.get("title", ""), doc.get("text", "")))
        if len(batch) >= BATCH:
            await flush()
        if (i + 1) % 500 == 0:
            pct = (i + 1) / total * 100
            elapsed = time.perf_counter() - t0
            print(f"  ingested {i + 1:>6} / {total} ({pct:5.1f}%, {elapsed:.1f}s)")

    await flush()
    print(f"  ingested {total} docs in {time.perf_counter() - t0:.1f}s")


def _dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def _ndcg_at_k(ranked_ids: list[str], relevant: dict[str, int], k: int) -> float:
    gains = [relevant.get(d, 0) for d in ranked_ids[:k]]
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = _dcg(ideal)
    return (_dcg(gains) / idcg) if idcg > 0 else 0.0


def _mrr(ranked_ids: list[str], relevant: set[str]) -> float:
    for i, d in enumerate(ranked_ids, 1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def _recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for d in ranked_ids[:k] if d in relevant)
    return hits / len(relevant)


def _hit_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(d in relevant for d in ranked_ids[:k]) else 0.0


async def score_queries(
    backend,
    queries: dict[str, str],
    qrels: dict[str, dict[str, int]],
    mode: str,
    k: int,
) -> dict[str, float]:
    from gnosis_mcp.local_embed import get_embedder  # noqa: E402

    embedder = get_embedder() if mode == "hybrid" else None

    n = 0
    ndcg10, mrr10, hit5, recall10 = 0.0, 0.0, 0.0, 0.0
    latencies_ms: list[float] = []

    for qid, qtext in queries.items():
        if qid not in qrels:
            continue
        relevant = {d: g for d, g in qrels[qid].items() if g > 0}
        if not relevant:
            continue
        relevant_ids = set(relevant)

        embedding = embedder.embed([qtext])[0] if embedder is not None else None

        t = time.perf_counter()
        hits = await backend.search(
            qtext,
            category=None,
            limit=k,
            query_embedding=embedding,
        )
        latencies_ms.append((time.perf_counter() - t) * 1000)

        ranked = [h["file_path"] for h in hits]
        ndcg10 += _ndcg_at_k(ranked, relevant, 10)
        mrr10 += _mrr(ranked, relevant_ids)
        hit5 += _hit_at_k(ranked, relevant_ids, 5)
        recall10 += _recall_at_k(ranked, relevant_ids, 10)
        n += 1

    latencies_ms.sort()

    def pct(p: float) -> float:
        if not latencies_ms:
            return 0.0
        i = min(len(latencies_ms) - 1, int(p * len(latencies_ms)))
        return latencies_ms[i]

    return {
        "queries": n,
        "ndcg_at_10": round(ndcg10 / max(n, 1), 4),
        "mrr_at_10": round(mrr10 / max(n, 1), 4),
        "hit_at_5": round(hit5 / max(n, 1), 4),
        "recall_at_10": round(recall10 / max(n, 1), 4),
        "p50_ms": round(pct(0.5), 2),
        "p95_ms": round(pct(0.95), 2),
        "p99_ms": round(pct(0.99), 2),
    }


async def run(dataset: str, mode: str, split: str, k: int, dataset_dir: Path) -> dict:
    util, GenericDataLoader = _try_beir_import()

    url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
    data_path = util.download_and_unzip(url, str(dataset_dir))

    corpus, queries, qrels = GenericDataLoader(data_folder=data_path).load(split=split)
    print(f"  loaded {len(corpus)} corpus docs, {len(queries)} queries ({split} split)")

    db_path = dataset_dir / f"gnosis-{dataset}-{mode}.db"
    if db_path.exists():
        db_path.unlink()

    # Match the vec0 table dim to the local embedder's output (384 for the
    # default MongoDB/mdbr-leaf-ir). Without this, inserts into the vec table
    # silently fail and hybrid mode degrades to keyword-only.
    cfg = GnosisMcpConfig(
        database_url=f"sqlite:///{db_path}",
        backend="sqlite",
        writable=True,
        embedding_dim=384 if mode == "hybrid" else 1536,
    )
    backend = create_backend(cfg)
    await backend.startup()
    await backend.init_schema()

    print(f"  ingesting into {db_path} (embed={'yes' if mode == 'hybrid' else 'no'}) …")
    await ingest_corpus(backend, corpus, embed=(mode == "hybrid"))

    print(f"  scoring {mode} search over {len(queries)} queries …")
    metrics = await score_queries(backend, queries, qrels, mode=mode, k=k)
    await backend.shutdown()
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="scifact", help="BEIR dataset name (default: scifact)")
    ap.add_argument("--split", default="test", help="Query split (default: test)")
    ap.add_argument("--mode", choices=["keyword", "hybrid"], default="hybrid")
    ap.add_argument("--k", type=int, default=10, help="Retrieval cutoff (default: 10)")
    ap.add_argument("--data-dir", default=None, help="Dataset cache dir (default: tmp)")
    ap.add_argument("--json", action="store_true", help="Emit JSON only")
    args = ap.parse_args()

    dataset_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.gettempdir()) / "beir-cache"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    metrics = asyncio.run(run(args.dataset, args.mode, args.split, args.k, dataset_dir))

    result = {
        "tool": "gnosis-mcp",
        "version": "0.10.13",
        "dataset": args.dataset,
        "split": args.split,
        "mode": args.mode,
        "k": args.k,
        **metrics,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print()
        print(f"  BEIR/{args.dataset}  —  {args.mode.upper()}")
        print(f"  ───────────────────────────────────────────")
        print(f"  queries         {result['queries']:>10}")
        print(f"  nDCG@10         {result['ndcg_at_10']:>10.4f}")
        print(f"  MRR@10          {result['mrr_at_10']:>10.4f}")
        print(f"  Hit@5           {result['hit_at_5']:>10.4f}")
        print(f"  Recall@10       {result['recall_at_10']:>10.4f}")
        print(f"  latency p50     {result['p50_ms']:>9.2f} ms")
        print(f"  latency p95     {result['p95_ms']:>9.2f} ms")
        print(f"  latency p99     {result['p99_ms']:>9.2f} ms")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
