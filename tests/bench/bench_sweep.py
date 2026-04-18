"""Multi-variable experiment sweep on BEIR datasets.

Runs gnosis-mcp through many configurations to find what actually moves
retrieval quality. Dimensions swept:

  - dataset: scifact (keyword-friendly), fiqa (paraphrase-heavy), nfcorpus
  - mode:    keyword | hybrid | keyword+rerank | hybrid+rerank | dense
  - chunk:   whole-doc | 500 char | 1000 char | 2000 char
  - title:   prepend | no
  - rrf_k:   30 | 60 | 100
  - embed:   mdbr-leaf-ir (default) | snowflake-arctic-embed-m-v1.5 (teacher)

Each experiment outputs one JSON line to stdout so results can be
jq-aggregated into a comparison table.

Usage:
  uv run --with beir --with 'gnosis-mcp[embeddings,reranking] @ .' \\
    python tests/bench/bench_sweep.py --preset reranker-impact
  uv run ... python tests/bench/bench_sweep.py --preset hybrid-datasets
  uv run ... python tests/bench/bench_sweep.py --preset title-ablation
  uv run ... python tests/bench/bench_sweep.py --preset asymmetric

Results land in ./bench-results/<preset>-<timestamp>.jsonl.
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
from dataclasses import asdict, dataclass, field
from pathlib import Path


# ─── Shared metric helpers ────────────────────────────────────────────────


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


def _pctile(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]


# ─── Experiment schema ────────────────────────────────────────────────────


@dataclass
class Config:
    dataset: str = "scifact"
    split: str = "test"
    mode: str = "keyword"       # keyword | hybrid | dense | keyword+rerank | hybrid+rerank
    chunk: str = "whole"        # whole | N where N ∈ {500,1000,2000}
    title: bool = False          # prepend title to content
    rrf_k: int = 60
    embed_model: str = "MongoDB/mdbr-leaf-ir"
    embed_dim: int = 384
    rerank_top_n: int = 50
    k: int = 10


@dataclass
class Result:
    config: dict = field(default_factory=dict)
    queries: int = 0
    ndcg_at_10: float = 0.0
    mrr_at_10: float = 0.0
    hit_at_5: float = 0.0
    recall_at_10: float = 0.0
    ingest_s: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0


# ─── BEIR loader ──────────────────────────────────────────────────────────


def load_beir(dataset: str, split: str, data_dir: Path):
    try:
        from beir import util  # type: ignore
        from beir.datasets.data_loader import GenericDataLoader  # type: ignore
    except ImportError as e:
        print("BEIR not installed. pip install beir", file=sys.stderr)
        raise SystemExit(2) from e
    url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
    path = util.download_and_unzip(url, str(data_dir))
    return GenericDataLoader(data_folder=path).load(split=split)


# ─── Chunk strategies ─────────────────────────────────────────────────────


def _chunk_doc(text: str, chunk: str) -> list[str]:
    """Return a list of chunks for one document."""
    text = text.strip()
    if not text:
        return []
    if chunk == "whole":
        return [text]
    size = int(chunk)
    # paragraph-boundary chunker, fallback to hard cut
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > size and buf:
            chunks.append(buf.strip())
            buf = ""
        buf = (buf + "\n\n" + para).strip() if buf else para
    if buf:
        chunks.append(buf.strip())
    # hard-cut any chunk still too big (e.g. no paragraph breaks)
    final: list[str] = []
    for c in chunks:
        while len(c) > size * 1.2:
            final.append(c[:size])
            c = c[size:]
        final.append(c)
    return final


# ─── Runner ───────────────────────────────────────────────────────────────


async def run_one(cfg: Config, corpus, queries, qrels, data_dir: Path) -> Result:
    """Execute one experimental config end-to-end."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig

    uses_dense = cfg.mode in ("hybrid", "dense", "hybrid+rerank")
    uses_rerank = "rerank" in cfg.mode

    # Build a deterministic DB path per config
    tag = (
        f"{cfg.dataset}-{cfg.mode}-chunk{cfg.chunk}-title{int(cfg.title)}-"
        f"rrf{cfg.rrf_k}-emb{cfg.embed_model.split('/')[-1]}"
    )
    db_path = data_dir / f"sweep-{tag}.db"
    if db_path.exists():
        db_path.unlink()

    gcfg = GnosisMcpConfig(
        database_url=f"sqlite:///{db_path}",
        backend="sqlite",
        writable=True,
        embedding_dim=cfg.embed_dim,
        embed_dim=cfg.embed_dim,
        rrf_k=cfg.rrf_k,
    )
    backend = create_backend(gcfg)
    await backend.startup()
    await backend.init_schema()

    # ── Ingest ────────────────────────────────────────────────────────────
    embedder = None
    if uses_dense:
        from gnosis_mcp.local_embed import LocalEmbedder

        embedder = LocalEmbedder(model_id=cfg.embed_model, dim=cfg.embed_dim)

    t0 = time.perf_counter()
    BATCH = 32
    ingest_items: list[tuple[str, str, list[str]]] = []  # (docid, title, chunks)
    for docid, doc in corpus.items():
        title = doc.get("title", "") or docid
        body = doc.get("text", "") or ""
        raw_chunks = _chunk_doc(body, cfg.chunk)
        if cfg.title and raw_chunks:
            raw_chunks = [f"{title}\n\n{c}" for c in raw_chunks]
        if not raw_chunks:
            raw_chunks = [title]
        ingest_items.append((docid, title, raw_chunks))

    for i in range(0, len(ingest_items), BATCH):
        sub = ingest_items[i : i + BATCH]
        # Flatten for batch embedding
        flat_chunks = [c for _, _, chunks in sub for c in chunks]
        if embedder is not None:
            flat_vecs = embedder.embed(flat_chunks)
        else:
            flat_vecs = None
        cursor = 0
        for docid, title, chunks in sub:
            emb_slice = None
            if flat_vecs is not None:
                emb_slice = flat_vecs[cursor : cursor + len(chunks)]
                cursor += len(chunks)
            await backend.upsert_doc(
                path=docid,
                chunks=chunks,
                title=title,
                category="beir",
                embeddings=emb_slice,
            )
    ingest_s = time.perf_counter() - t0

    # ── Score queries ─────────────────────────────────────────────────────
    reranker = None
    if uses_rerank:
        from gnosis_mcp.rerank import get_reranker

        # onnx-community/ms-marco-MiniLM-L6-v2-ONNX returned 401 as of 2026-04
        # (repo gated/moved). Use the canonical cross-encoder repo which also
        # ships ONNX exports under onnx/model.onnx.
        reranker = get_reranker(model="cross-encoder/ms-marco-MiniLM-L6-v2")

    ranked_cache: dict[str, list[str]] = {}
    lats: list[float] = []

    for qid, qtext in queries.items():
        if qid not in qrels:
            continue
        qvec = None
        if uses_dense and embedder is not None:
            qvec = embedder.embed([qtext])[0]
        fetch_n = cfg.rerank_top_n if uses_rerank else cfg.k
        t1 = time.perf_counter()
        hits = await backend.search(qtext, limit=fetch_n, query_embedding=qvec)
        if uses_rerank and hits:
            hits = reranker.rerank(qtext, hits, text_key="content", top_k=cfg.k)
        lats.append((time.perf_counter() - t1) * 1000)
        # Deduplicate doc IDs (preserve rank of first occurrence) since multi-chunk
        # docs can emit the same file_path twice in top-N.
        seen: set[str] = set()
        deduped: list[str] = []
        for h in hits:
            path = h["file_path"]
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)
            if len(deduped) >= cfg.k:
                break
        ranked_cache[qid] = deduped

    await backend.shutdown()
    if db_path.exists():
        db_path.unlink()

    # ── Aggregate ────────────────────────────────────────────────────────
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
        ndcg += _ndcg_at_k(ranked, relevant, cfg.k)
        mrr += _mrr(ranked, rel_ids)
        hit5 += _hit_at_k(ranked, rel_ids, 5)
        recall += _recall_at_k(ranked, rel_ids, cfg.k)
        n += 1

    return Result(
        config=asdict(cfg),
        queries=n,
        ndcg_at_10=round(ndcg / max(n, 1), 4),
        mrr_at_10=round(mrr / max(n, 1), 4),
        hit_at_5=round(hit5 / max(n, 1), 4),
        recall_at_10=round(recall / max(n, 1), 4),
        ingest_s=round(ingest_s, 1),
        p50_ms=round(_pctile(lats, 0.5), 2),
        p95_ms=round(_pctile(lats, 0.95), 2),
    )


# ─── Presets ──────────────────────────────────────────────────────────────


def preset_reranker_impact(dataset: str) -> list[Config]:
    """How much does the cross-encoder reranker add to each mode?"""
    modes = ["keyword", "keyword+rerank", "hybrid", "hybrid+rerank"]
    return [Config(dataset=dataset, mode=m) for m in modes]


def preset_hybrid_datasets() -> list[Config]:
    """Does hybrid help more on paraphrase-heavy datasets?"""
    out = []
    for ds in ("scifact", "fiqa", "nfcorpus"):
        for m in ("keyword", "hybrid", "hybrid+rerank"):
            out.append(Config(dataset=ds, mode=m))
    return out


def preset_title_ablation(dataset: str) -> list[Config]:
    """Does prepending title to each chunk help?"""
    out = []
    for mode in ("keyword", "hybrid"):
        for title in (False, True):
            out.append(Config(dataset=dataset, mode=mode, title=title))
    return out


def preset_rrf_k_sweep(dataset: str) -> list[Config]:
    """Optimal RRF k on this dataset?"""
    return [
        Config(dataset=dataset, mode="hybrid", rrf_k=k)
        for k in (20, 40, 60, 80, 100)
    ]


def preset_chunk_ablation(dataset: str) -> list[Config]:
    """Chunk size effect on hybrid retrieval."""
    return [
        Config(dataset=dataset, mode="hybrid", chunk=c)
        for c in ("whole", "2000", "1000", "500")
    ]


def preset_embed_model() -> list[Config]:
    """Different embedders — apples-to-apples on SciFact."""
    return [
        Config(dataset="scifact", mode="hybrid",
               embed_model="MongoDB/mdbr-leaf-ir", embed_dim=384),
        # Teacher (snowflake, 109M) — aligned by construction
        Config(dataset="scifact", mode="hybrid",
               embed_model="Snowflake/snowflake-arctic-embed-m-v1.5",
               embed_dim=768),
    ]


PRESETS = {
    "reranker-impact-scifact": lambda: preset_reranker_impact("scifact"),
    "reranker-impact-fiqa": lambda: preset_reranker_impact("fiqa"),
    "hybrid-datasets": preset_hybrid_datasets,
    "title-scifact": lambda: preset_title_ablation("scifact"),
    "title-fiqa": lambda: preset_title_ablation("fiqa"),
    "rrf-k-fiqa": lambda: preset_rrf_k_sweep("fiqa"),
    "chunk-fiqa": lambda: preset_chunk_ablation("fiqa"),
    "embed-model": preset_embed_model,
}


# ─── CLI ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", required=True, choices=list(PRESETS))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--out", default=None, help="Output JSONL file")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.gettempdir()) / "beir-cache"
    data_dir.mkdir(parents=True, exist_ok=True)

    configs = PRESETS[args.preset]()

    # Group by dataset so we only load each BEIR corpus once
    out_path = Path(args.out) if args.out else Path("bench-results") / f"{args.preset}-{int(time.time())}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cached_datasets: dict[str, tuple] = {}
    results: list[Result] = []

    for i, cfg in enumerate(configs, 1):
        print(f"\n  [{i}/{len(configs)}] {cfg.dataset} · {cfg.mode} · chunk={cfg.chunk} · title={cfg.title} · rrf_k={cfg.rrf_k} · {cfg.embed_model.split('/')[-1]}")
        if cfg.dataset not in cached_datasets:
            cached_datasets[cfg.dataset] = load_beir(cfg.dataset, cfg.split, data_dir)
        corpus, queries, qrels = cached_datasets[cfg.dataset]
        try:
            res = asyncio.run(run_one(cfg, corpus, queries, qrels, data_dir))
            print(
                f"    → nDCG@10={res.ndcg_at_10:.4f}  MRR@10={res.mrr_at_10:.4f}  "
                f"Hit@5={res.hit_at_5:.4f}  Recall@10={res.recall_at_10:.4f}  "
                f"p95={res.p95_ms}ms  ingest={res.ingest_s}s"
            )
            results.append(res)
            with out_path.open("a") as f:
                f.write(json.dumps({"config": res.config, **{k: v for k, v in asdict(res).items() if k != 'config'}}) + "\n")
        except Exception as exc:  # noqa: BLE001
            print(f"    ✗ ERROR: {type(exc).__name__}: {exc}")

    print(f"\n  Results → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
