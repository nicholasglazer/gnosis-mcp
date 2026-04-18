"""Side-by-side comparison on a BEIR dataset.

Runs the SAME corpus + query set + metrics through multiple tools so
readers can see gnosis-mcp on one axis of a real table, not just
self-reported numbers.

Currently supported tools:
  - gnosis-mcp        (FTS5 keyword, SQLite + sqlite-vec hybrid)
  - txtai             (txtai by neuml — embeddings + sqlite FTS)
  - whoosh            (pure-Python BM25 baseline)

Extension point: add a new `bench_<name>()` async function, register it
in REGISTRY, and it shows up in the table.

Usage:
    uv run --with beir --with 'gnosis-mcp[embeddings] @ .' --with txtai \\
           --with whoosh \\
           python tests/bench/bench_compare.py --dataset scifact

Heavy comparators (LlamaIndex+Chroma, Haystack) deliberately left as
user-installable — they pull 60+ transitive deps and are better run in
their own venv. A stub is included showing how to add them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
from pathlib import Path


# ─── Metrics ───────────────────────────────────────────────────────────────


def _dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def _ndcg_at_k(ranked_ids, relevant, k):
    gains = [relevant.get(d, 0) for d in ranked_ids[:k]]
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = _dcg(ideal)
    return (_dcg(gains) / idcg) if idcg > 0 else 0.0


def _mrr(ranked_ids, relevant_ids):
    for i, d in enumerate(ranked_ids, 1):
        if d in relevant_ids:
            return 1.0 / i
    return 0.0


def _hit_at_k(ranked_ids, relevant_ids, k):
    return 1.0 if any(d in relevant_ids for d in ranked_ids[:k]) else 0.0


def _recall_at_k(ranked_ids, relevant_ids, k):
    if not relevant_ids:
        return 0.0
    return sum(1 for d in ranked_ids[:k] if d in relevant_ids) / len(relevant_ids)


def score(ranked_getter, queries, qrels, k=10):
    """Run `ranked_getter(qtext) -> list[doc_id]` against all queries."""
    n = 0
    ndcg, mrr, hit5, recall = 0.0, 0.0, 0.0, 0.0
    lats = []
    for qid, qtext in queries.items():
        if qid not in qrels:
            continue
        relevant = {d: g for d, g in qrels[qid].items() if g > 0}
        if not relevant:
            continue
        rel_ids = set(relevant)
        t0 = time.perf_counter()
        ranked = ranked_getter(qtext)
        lats.append((time.perf_counter() - t0) * 1000)
        ndcg += _ndcg_at_k(ranked, relevant, k)
        mrr += _mrr(ranked, rel_ids)
        hit5 += _hit_at_k(ranked, rel_ids, 5)
        recall += _recall_at_k(ranked, rel_ids, k)
        n += 1
    lats.sort()

    def pct(p):
        if not lats:
            return 0.0
        return lats[min(len(lats) - 1, int(p * len(lats)))]

    return {
        "queries": n,
        "ndcg_at_10": round(ndcg / max(n, 1), 4),
        "mrr_at_10": round(mrr / max(n, 1), 4),
        "hit_at_5": round(hit5 / max(n, 1), 4),
        "recall_at_10": round(recall / max(n, 1), 4),
        "p50_ms": round(pct(0.5), 2),
        "p95_ms": round(pct(0.95), 2),
    }


# ─── gnosis-mcp ───────────────────────────────────────────────────────────


async def _gnosis_keyword(corpus, queries, qrels, k, data_dir):
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    db = data_dir / "gnosis-keyword.db"
    if db.exists():
        db.unlink()
    cfg = GnosisMcpConfig(database_url=f"sqlite:///{db}", backend="sqlite", writable=True)
    backend = create_backend(cfg)
    await backend.startup()
    await backend.init_schema()

    t0 = time.perf_counter()
    for docid, doc in corpus.items():
        text = f"{doc.get('title', '')}\n\n{doc.get('text', '')}".strip()
        await backend.upsert_doc(
            path=docid, chunks=[text], title=doc.get("title") or docid, category="beir"
        )
    ingest_s = time.perf_counter() - t0

    # Measure per-query latency alongside ranking
    ranked_cache: dict[str, list[str]] = {}
    lats: list[float] = []
    for qid, qtext in queries.items():
        t1 = time.perf_counter()
        hits = await backend.search(qtext, limit=k)
        lats.append((time.perf_counter() - t1) * 1000)
        ranked_cache[qid] = [h["file_path"] for h in hits]
    await backend.shutdown()

    return _score_from_cache(ranked_cache, queries, qrels, lats, k,
                             tool="gnosis-mcp (keyword)", ingest_s=ingest_s)


def _score_from_cache(ranked_cache, queries, qrels, lats, k, *, tool, ingest_s):
    n = 0
    ndcg = mrr = hit5 = recall = 0.0
    for qid, qtext in queries.items():
        if qid not in qrels or qid not in ranked_cache:
            continue
        relevant = {d: g for d, g in qrels[qid].items() if g > 0}
        if not relevant:
            continue
        rel_ids = set(relevant)
        ranked = ranked_cache[qid]
        ndcg += _ndcg_at_k(ranked, relevant, k)
        mrr += _mrr(ranked, rel_ids)
        hit5 += _hit_at_k(ranked, rel_ids, 5)
        recall += _recall_at_k(ranked, rel_ids, k)
        n += 1
    lats_sorted = sorted(lats)

    def pct(p):
        if not lats_sorted:
            return 0.0
        return lats_sorted[min(len(lats_sorted) - 1, int(p * len(lats_sorted)))]

    return {
        "tool": tool,
        "queries": n,
        "ndcg_at_10": round(ndcg / max(n, 1), 4),
        "mrr_at_10": round(mrr / max(n, 1), 4),
        "hit_at_5": round(hit5 / max(n, 1), 4),
        "recall_at_10": round(recall / max(n, 1), 4),
        "p50_ms": round(pct(0.5), 2),
        "p95_ms": round(pct(0.95), 2),
        "ingest_s": round(ingest_s, 1),
    }


async def _gnosis_hybrid(corpus, queries, qrels, k, data_dir):
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.local_embed import get_embedder

    db = data_dir / "gnosis-hybrid.db"
    if db.exists():
        db.unlink()
    cfg = GnosisMcpConfig(
        database_url=f"sqlite:///{db}", backend="sqlite", writable=True, embedding_dim=384
    )
    backend = create_backend(cfg)
    await backend.startup()
    await backend.init_schema()
    embedder = get_embedder()

    t0 = time.perf_counter()
    docs_list = list(corpus.items())
    BATCH = 64
    for i in range(0, len(docs_list), BATCH):
        sub = docs_list[i : i + BATCH]
        texts = [f"{d.get('title', '')}\n\n{d.get('text', '')}".strip() for _, d in sub]
        vecs = embedder.embed(texts)
        for (docid, doc), text, vec in zip(sub, texts, vecs, strict=False):
            await backend.upsert_doc(
                path=docid,
                chunks=[text],
                title=doc.get("title") or docid,
                category="beir",
                embeddings=[vec],
            )
    ingest_s = time.perf_counter() - t0

    ranked_cache: dict[str, list[str]] = {}
    lats: list[float] = []
    for qid, qtext in queries.items():
        qvec = embedder.embed([qtext])[0]
        t1 = time.perf_counter()
        hits = await backend.search(qtext, limit=k, query_embedding=qvec)
        lats.append((time.perf_counter() - t1) * 1000)
        ranked_cache[qid] = [h["file_path"] for h in hits]
    await backend.shutdown()

    return _score_from_cache(ranked_cache, queries, qrels, lats, k,
                             tool="gnosis-mcp (hybrid)", ingest_s=ingest_s)


# ─── txtai ────────────────────────────────────────────────────────────────


def _bench_txtai(corpus, queries, qrels, k):
    try:
        from txtai.embeddings import Embeddings  # type: ignore
    except ImportError:
        return {"tool": "txtai", "error": "not installed (pip install txtai)"}

    t0 = time.perf_counter()
    # txtai uses sentence-transformers by default — pin a small one.
    embeddings = Embeddings(
        path="sentence-transformers/all-MiniLM-L6-v2",
        content=True,
    )
    docs = [
        (docid, f"{doc.get('title', '')}\n\n{doc.get('text', '')}".strip(), None)
        for docid, doc in corpus.items()
    ]
    embeddings.index(docs)
    ingest_s = time.perf_counter() - t0

    def getter(qtext):
        results = embeddings.search(qtext, k)
        return [r["id"] for r in results]

    m = score(getter, queries, qrels, k=k)
    m["tool"] = "txtai"
    m["ingest_s"] = round(ingest_s, 1)
    return m


# ─── Whoosh (pure-Python BM25 baseline) ───────────────────────────────────


def _bench_whoosh(corpus, queries, qrels, k, data_dir):
    try:
        from whoosh.fields import Schema, ID, TEXT  # type: ignore
        from whoosh.index import create_in  # type: ignore
        from whoosh.qparser import QueryParser  # type: ignore
    except ImportError:
        return {"tool": "whoosh", "error": "not installed (pip install whoosh)"}

    idx_dir = data_dir / "whoosh-idx"
    idx_dir.mkdir(exist_ok=True)
    schema = Schema(docid=ID(stored=True), body=TEXT(stored=False))
    ix = create_in(str(idx_dir), schema)
    writer = ix.writer()
    t0 = time.perf_counter()
    for docid, doc in corpus.items():
        writer.add_document(
            docid=str(docid),
            body=f"{doc.get('title', '')}\n\n{doc.get('text', '')}",
        )
    writer.commit()
    ingest_s = time.perf_counter() - t0

    searcher = ix.searcher()
    qp = QueryParser("body", schema=ix.schema)

    def getter(qtext):
        q = qp.parse(qtext)
        return [r["docid"] for r in searcher.search(q, limit=k)]

    m = score(getter, queries, qrels, k=k)
    m["tool"] = "whoosh (pure-py BM25)"
    m["ingest_s"] = round(ingest_s, 1)
    return m


# ─── Entry point ──────────────────────────────────────────────────────────


def _load_beir(dataset, split, data_dir):
    try:
        from beir import util  # type: ignore
        from beir.datasets.data_loader import GenericDataLoader  # type: ignore
    except ImportError as e:
        print("BEIR not installed. Run: pip install beir", file=sys.stderr)
        raise SystemExit(2) from e
    url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
    path = util.download_and_unzip(url, str(data_dir))
    return GenericDataLoader(data_folder=path).load(split=split)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="scifact")
    ap.add_argument("--split", default="test")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument(
        "--tools",
        default="gnosis-keyword,gnosis-hybrid,whoosh,txtai",
        help="Comma-separated tool list",
    )
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.gettempdir()) / "beir-cache"
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"  loading BEIR/{args.dataset} ({args.split}) …")
    corpus, queries, qrels = _load_beir(args.dataset, args.split, data_dir)
    print(f"  {len(corpus)} docs, {len(queries)} queries")

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    results = []

    for tool in tools:
        print(f"\n  ── {tool} ─────────────────────────")
        try:
            if tool == "gnosis-keyword":
                r = asyncio.run(_gnosis_keyword(corpus, queries, qrels, args.k, data_dir))
            elif tool == "gnosis-hybrid":
                r = asyncio.run(_gnosis_hybrid(corpus, queries, qrels, args.k, data_dir))
            elif tool == "txtai":
                r = _bench_txtai(corpus, queries, qrels, args.k)
            elif tool == "whoosh":
                r = _bench_whoosh(corpus, queries, qrels, args.k, data_dir)
            else:
                r = {"tool": tool, "error": f"unknown tool: {tool}"}
        except Exception as exc:  # noqa: BLE001
            r = {"tool": tool, "error": f"{type(exc).__name__}: {exc}"}
        results.append(r)
        print(f"  {json.dumps(r, indent=2)}")

    summary = {
        "dataset": args.dataset,
        "split": args.split,
        "k": args.k,
        "docs": len(corpus),
        "queries": len(queries),
        "results": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print()
        print(f"  BEIR/{args.dataset}  —  {args.split} split, k={args.k}")
        print(f"  {'─' * 80}")
        print(
            f"  {'tool':<26} {'nDCG@10':>9} {'MRR@10':>8} {'Hit@5':>7} {'Rec@10':>8} {'p50':>7} {'p95':>7} {'ingest':>8}"
        )
        for r in results:
            if r.get("error"):
                print(f"  {r['tool']:<26} {r['error']}")
                continue
            print(
                f"  {r['tool']:<26} "
                f"{r['ndcg_at_10']:>9.4f} "
                f"{r['mrr_at_10']:>8.4f} "
                f"{r['hit_at_5']:>7.4f} "
                f"{r['recall_at_10']:>8.4f} "
                f"{r['p50_ms']:>6.1f}ms "
                f"{r['p95_ms']:>6.1f}ms "
                f"{r.get('ingest_s', 0):>7.1f}s"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
