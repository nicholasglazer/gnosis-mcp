"""Real-world retrieval quality on a developer-docs corpus.

BEIR gives us external validity; this gives us in-distribution validity —
"does gnosis-mcp's default config actually find the right doc when a dev
asks our own knowledge base?"

How it works:
  1. Ingest an arbitrary markdown corpus (--corpus path).
  2. Load a golden set: {"query": "...", "expected_paths": ["docs/x.md",...]}.
  3. Run each query through every mode (keyword, hybrid, +rerank).
  4. Score with Hit@5, MRR@10, nDCG@10.

Golden set format (golden.jsonl, one object per line):
  {"query": "how does the reranker work", "expected_paths": ["docs/config.md", "docs/tools.md"]}

Usage:
  uv run --with 'gnosis-mcp[embeddings,reranking] @ .' \\
    python tests/bench/bench_real_corpus.py \\
      --corpus /home/ng/prod/knowledge \\
      --golden tests/bench/golden-knowledge.jsonl

Relevance judgement: a hit is when ANY expected path appears (substring
match) in the top-k returned file paths. This is more forgiving than BEIR's
exact-docid matching — appropriate for real-world RAG where path layouts
aren't identical to query phrasing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GoldenCase:
    query: str
    expected_paths: list[str]
    description: str = ""


def _matches(path: str, expected_patterns: list[str]) -> bool:
    for pat in expected_patterns:
        if pat.lower() in path.lower():
            return True
    return False


def _hit_at_k(ranked: list[str], expected: list[str], k: int) -> float:
    return 1.0 if any(_matches(p, expected) for p in ranked[:k]) else 0.0


def _mrr(ranked: list[str], expected: list[str]) -> float:
    for i, p in enumerate(ranked, 1):
        if _matches(p, expected):
            return 1.0 / i
    return 0.0


def _ndcg_at_k(ranked: list[str], expected: list[str], k: int) -> float:
    # Single-level relevance (match = 1, no-match = 0) — nDCG reduces to a
    # discounted hit metric.
    gains = [1.0 if _matches(p, expected) else 0.0 for p in ranked[:k]]

    def _dcg(gs):
        return sum(g / math.log2(i + 2) for i, g in enumerate(gs))

    ideal = [1.0] + [0.0] * (k - 1) if expected else []
    idcg = _dcg(ideal)
    return (_dcg(gains) / idcg) if idcg > 0 else 0.0


def _pctile(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]


async def ingest_corpus(backend, corpus_root: Path, embedder, title_prepend: bool = False) -> int:
    """Walk `corpus_root`, ingest every .md file as its own doc."""
    from gnosis_mcp.ingest import chunk_by_headings

    files = sorted(p for p in corpus_root.rglob("*.md") if p.is_file())
    count = 0
    BATCH = 32
    staged: list[tuple[str, str, list[str]]] = []

    async def _flush():
        nonlocal staged, count
        if not staged:
            return
        flat_chunks = [c for _, _, chs in staged for c in chs]
        embs = embedder.embed(flat_chunks) if embedder else None
        cursor = 0
        for rel, title, chs in staged:
            slice_ = embs[cursor : cursor + len(chs)] if embs else None
            cursor += len(chs)
            await backend.upsert_doc(
                path=rel,
                chunks=chs,
                title=title or rel,
                category=rel.split("/")[0] if "/" in rel else "root",
                embeddings=slice_,
            )
            count += 1
        staged = []

    for f in files:
        try:
            body = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = str(f.relative_to(corpus_root))
        title = f.stem.replace("-", " ").replace("_", " ").title()
        chunk_dicts = chunk_by_headings(body, file_path=rel, max_chunk_size=4000)
        chunks = [c.get("content", "") for c in chunk_dicts if c.get("content")]
        if not chunks:
            chunks = [body.strip()[:4000]]
        if title_prepend:
            chunks = [f"{title}\n{rel}\n\n{c}" for c in chunks]
        staged.append((rel, title, chunks))
        if len(staged) >= BATCH:
            await _flush()
    await _flush()
    return count


async def run_mode(
    backend, embedder, reranker, cases: list[GoldenCase], mode: str, k: int, rerank_n: int
):
    uses_dense = mode in ("hybrid", "dense", "hybrid+rerank")
    uses_rerank = "rerank" in mode

    ranked_map: dict[str, list[str]] = {}
    lats: list[float] = []

    for case in cases:
        qvec = embedder.embed([case.query])[0] if (uses_dense and embedder) else None
        fetch_n = rerank_n if uses_rerank else k
        t0 = time.perf_counter()
        hits = await backend.search(case.query, limit=fetch_n, query_embedding=qvec)
        if uses_rerank and hits:
            hits = reranker.rerank(case.query, hits, text_key="content", top_k=k)
        lats.append((time.perf_counter() - t0) * 1000)

        seen: set[str] = set()
        deduped: list[str] = []
        for h in hits:
            p = h["file_path"]
            if p in seen:
                continue
            seen.add(p)
            deduped.append(p)
            if len(deduped) >= k:
                break
        ranked_map[case.query] = deduped

    hit5 = sum(_hit_at_k(ranked_map[c.query], c.expected_paths, 5) for c in cases) / max(len(cases), 1)
    hit10 = sum(_hit_at_k(ranked_map[c.query], c.expected_paths, 10) for c in cases) / max(len(cases), 1)
    mrr = sum(_mrr(ranked_map[c.query], c.expected_paths) for c in cases) / max(len(cases), 1)
    ndcg = sum(_ndcg_at_k(ranked_map[c.query], c.expected_paths, k) for c in cases) / max(len(cases), 1)

    return {
        "mode": mode,
        "queries": len(cases),
        "hit_at_5": round(hit5, 4),
        "hit_at_10": round(hit10, 4),
        "mrr": round(mrr, 4),
        "ndcg_at_10": round(ndcg, 4),
        "p50_ms": round(_pctile(lats, 0.5), 2),
        "p95_ms": round(_pctile(lats, 0.95), 2),
        "per_query": {
            c.query: ranked_map[c.query] for c in cases
        },
    }


async def main_async(args) -> int:
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.local_embed import LocalEmbedder
    from gnosis_mcp.rerank import get_reranker

    # Load golden set
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

    corpus_root = Path(args.corpus).resolve()
    if not corpus_root.is_dir():
        print(f"  corpus path not a directory: {corpus_root}", file=sys.stderr)
        return 2

    db_path = Path(tempfile.gettempdir()) / f"gnosis-real-{int(time.time())}.db"
    cfg = GnosisMcpConfig(
        database_url=f"sqlite:///{db_path}",
        backend="sqlite",
        writable=True,
        embedding_dim=384,
        embed_dim=384,
    )
    backend = create_backend(cfg)
    await backend.startup()
    await backend.init_schema()

    embedder = LocalEmbedder(dim=384)
    reranker = get_reranker(model=args.rerank_model)

    print(f"  ingesting {corpus_root} (title_prepend={args.title_prepend}) …")
    t0 = time.perf_counter()
    doc_count = await ingest_corpus(backend, corpus_root, embedder, args.title_prepend)
    ingest_s = time.perf_counter() - t0
    print(f"  ingested {doc_count} docs in {ingest_s:.1f}s")

    results = []
    for mode in args.modes.split(","):
        mode = mode.strip()
        r = await run_mode(backend, embedder, reranker, cases, mode=mode, k=args.k, rerank_n=args.rerank_n)
        print(
            f"  {mode:18s}  nDCG={r['ndcg_at_10']:.4f}  MRR={r['mrr']:.4f}  Hit@5={r['hit_at_5']:.4f}  "
            f"Hit@10={r['hit_at_10']:.4f}  p95={r['p95_ms']}ms"
        )
        results.append(r)

    await backend.shutdown()
    if db_path.exists():
        db_path.unlink()

    out = {
        "corpus": str(corpus_root),
        "docs": doc_count,
        "ingest_s": round(ingest_s, 1),
        "golden_cases": len(cases),
        "title_prepend": args.title_prepend,
        "results": results,
    }
    out_path = Path(args.out) if args.out else Path("bench-results") / f"real-corpus-{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"  → {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, help="Root of markdown corpus")
    ap.add_argument("--golden", required=True, help="golden.jsonl — query/expected_paths")
    ap.add_argument(
        "--modes", default="keyword,hybrid,hybrid+rerank",
        help="Comma-separated modes to test",
    )
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--rerank-n", type=int, default=50)
    ap.add_argument("--title-prepend", action="store_true",
                    help="Prepend file title + path to each chunk (often +2-5 points)")
    ap.add_argument("--rerank-model",
                    default="cross-encoder/ms-marco-MiniLM-L6-v2",
                    help="HF repo for the cross-encoder (e.g. BAAI/bge-reranker-base)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
