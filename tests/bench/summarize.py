"""Aggregate all bench-results/*.jsonl into a single comparison table.

Usage:
    python tests/bench/summarize.py [--pattern "bench-results/*.jsonl"]
"""

from __future__ import annotations

import argparse
import glob
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="bench-results/*.jsonl")
    ap.add_argument("--sort", default="ndcg_at_10")
    args = ap.parse_args()

    rows = []
    for path in sorted(glob.glob(args.pattern)):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    c = r.get("config", {})
                    rows.append(
                        {
                            "dataset": c.get("dataset", "?"),
                            "mode": c.get("mode", "?"),
                            "chunk": c.get("chunk", "?"),
                            "title": c.get("title", False),
                            "rrf_k": c.get("rrf_k", 60),
                            "embed": (c.get("embed_model") or "").split("/")[-1] or "?",
                            "ndcg_at_10": r.get("ndcg_at_10"),
                            "mrr_at_10": r.get("mrr_at_10"),
                            "hit_at_5": r.get("hit_at_5"),
                            "recall_at_10": r.get("recall_at_10"),
                            "p50_ms": r.get("p50_ms"),
                            "p95_ms": r.get("p95_ms"),
                            "ingest_s": r.get("ingest_s"),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {path}: {exc}")

    rows.sort(key=lambda r: (r["dataset"], -(r[args.sort] or 0)))

    print(
        f"  {'dataset':<10} {'mode':<16} {'chunk':<6} {'title':<5} {'embed':<22} "
        f"{'nDCG@10':>8} {'MRR':>7} {'Hit@5':>7} {'Rec@10':>7} {'p95':>7} {'ingest':>8}"
    )
    print("  " + "─" * 120)
    prev_ds = None
    for r in rows:
        if prev_ds is not None and r["dataset"] != prev_ds:
            print("  " + "─" * 120)
        prev_ds = r["dataset"]
        title_c = "✓" if r["title"] else "—"
        print(
            f"  {r['dataset']:<10} {r['mode']:<16} {r['chunk']:<6} {title_c:<5} {r['embed']:<22} "
            f"{r['ndcg_at_10']:>8.4f} {r['mrr_at_10']:>7.4f} {r['hit_at_5']:>7.4f} "
            f"{r['recall_at_10']:>7.4f} {r['p95_ms']:>6.1f}ms {r['ingest_s']:>7.1f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
