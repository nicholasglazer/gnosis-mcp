"""One-shot sweep to show effect of v0.11.7+ search knobs vs pre-v0.11.7 default.

Scratch script — not committed. Runs the same goldens through the same corpus
four times, varying GNOSIS_MCP_COLLAPSE_BY_DOC and GNOSIS_MCP_MMR_LAMBDA. Uses
the real server.search_docs pipeline (not the lower-level backend.search that
bench_existing_db.py uses) so the post-processors (MMR, collapse-by-doc) are
actually exercised.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bench_real_corpus import GoldenCase, _hit_at_k, _mrr, _ndcg_at_k, _pctile  # noqa: E402


async def run_config(
    golden_path: str,
    *,
    collapse: bool,
    mmr_lambda: float,
    k: int = 10,
    rerank_pool: int = 20,
) -> dict:
    # Fresh env per-config so GnosisMcpConfig picks up the right values.
    os.environ["GNOSIS_MCP_COLLAPSE_BY_DOC"] = "true" if collapse else "false"
    os.environ["GNOSIS_MCP_MMR_LAMBDA"] = str(mmr_lambda)
    os.environ["GNOSIS_MCP_EMBED_PROVIDER"] = "local"
    # Importing inside so the env is set before from_env().
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.config import GnosisMcpConfig
    from gnosis_mcp.embed import embed_texts
    from gnosis_mcp.server import _apply_mmr, _collapse_by_doc

    cases: list[GoldenCase] = []
    with open(golden_path) as f:
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

    cfg = GnosisMcpConfig.from_env()
    backend = create_backend(cfg)
    await backend.startup()

    ranked_map: dict[str, list[str]] = {}
    lats: list[float] = []
    fetch_n = rerank_pool
    if cfg.collapse_by_doc:
        fetch_n = max(fetch_n, k * 5)
    if 0.0 < cfg.mmr_lambda < 1.0:
        fetch_n = max(fetch_n, k * 5)

    try:
        for case in cases:
            qvec = embed_texts(
                [case.query], provider="local", model=cfg.embed_model, dim=cfg.embed_dim
            )[0]
            t0 = time.perf_counter()
            results = await backend.search(
                case.query, limit=fetch_n, query_embedding=qvec
            )

            if 0.0 < cfg.mmr_lambda < 1.0 and len(results) > 1:
                doc_vecs = embed_texts(
                    [r.get("content", "") for r in results],
                    provider="local",
                    model=cfg.embed_model,
                    dim=cfg.embed_dim,
                )
                results = _apply_mmr(results, qvec, doc_vecs, cfg.mmr_lambda)
            if cfg.collapse_by_doc:
                results = _collapse_by_doc(results)
            results = results[:k]
            lats.append((time.perf_counter() - t0) * 1000)

            seen: set[str] = set()
            ranked: list[str] = []
            for r in results:
                fp = r["file_path"]
                if fp in seen:
                    continue
                seen.add(fp)
                ranked.append(fp)
            ranked_map[case.query] = ranked

        hit5 = sum(_hit_at_k(ranked_map[c.query], c.expected_paths, 5) for c in cases) / len(cases)
        mrr = sum(_mrr(ranked_map[c.query], c.expected_paths) for c in cases) / len(cases)
        ndcg = sum(_ndcg_at_k(ranked_map[c.query], c.expected_paths, k) for c in cases) / len(cases)

        # Diversity: mean distinct file_paths in top-5 across goldens.
        div = sum(len(set(ranked_map[c.query][:5])) for c in cases) / len(cases)

        return {
            "collapse": collapse,
            "mmr_lambda": mmr_lambda,
            "hit_at_5": round(hit5, 4),
            "mrr": round(mrr, 4),
            "ndcg_at_10": round(ndcg, 4),
            "p50_ms": round(_pctile(lats, 0.5), 1),
            "p95_ms": round(_pctile(lats, 0.95), 1),
            "distinct_in_top5": round(div, 2),
        }
    finally:
        await backend.shutdown()


async def main() -> int:
    golden = sys.argv[1] if len(sys.argv) > 1 else "tests/bench/golden-laptop.jsonl"
    configs = [
        ("A  default",                 False, 1.0),
        ("B  collapse_by_doc=true",    True,  1.0),
        ("C  mmr=0.6",                 False, 0.6),
        ("D  collapse + mmr=0.6",      True,  0.6),
    ]
    rows = []
    for label, collapse, lmbda in configs:
        r = await run_config(golden, collapse=collapse, mmr_lambda=lmbda)
        r["label"] = label
        rows.append(r)

    print("\n  Hybrid-mode sweep, 30 goldens, same corpus + embedder (mdbr-leaf-ir @ 384)")
    print("  " + "=" * 88)
    print(f"  {'config':<30}  {'nDCG@10':>8} {'MRR':>6} {'Hit@5':>6} {'p50ms':>7} {'p95ms':>7} {'div5':>6}")
    print("  " + "-" * 88)
    for r in rows:
        print(
            f"  {r['label']:<30}  {r['ndcg_at_10']:>8.4f} "
            f"{r['mrr']:>6.4f} {r['hit_at_5']:>6.4f} "
            f"{r['p50_ms']:>7.1f} {r['p95_ms']:>7.1f} {r['distinct_in_top5']:>6.2f}"
        )
    print("  " + "=" * 88)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
