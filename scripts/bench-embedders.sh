#!/usr/bin/env bash
# Benchmark four embedders on the real /knowledge corpus.
# Emits one JSON file per model into bench-results/ and a summary at the end.
#
# Usage: scripts/bench-embedders.sh
#
# Runtime: ~60-90 min on laptop CPU depending on model size.

set -euo pipefail
cd "$(dirname "$0")/.."

CORPUS="${CORPUS:-/home/ng/prod/knowledge}"
GOLDEN="${GOLDEN:-tests/bench/golden-knowledge.jsonl}"
TS=$(date +%s)
OUTDIR="bench-results/embedders-${TS}"
mkdir -p "$OUTDIR"

# Model sweep. Each: <out-name> <hf-id> <dim>
# Dimensions chosen to match each model's native output for a fair shoot-out.
SWEEP=(
  "mdbr-leaf-ir|MongoDB/mdbr-leaf-ir|384"
  "mxbai-large|mixedbread-ai/mxbai-embed-large-v1|1024"
  "bge-large|BAAI/bge-large-en-v1.5|1024"
  "nomic-text|nomic-ai/nomic-embed-text-v1.5|768"
)

for entry in "${SWEEP[@]}"; do
  IFS='|' read -r NAME MODEL DIM <<< "$entry"
  OUT="$OUTDIR/${NAME}.json"
  echo ""
  echo "============================================================"
  echo "[$NAME] model=$MODEL dim=$DIM"
  echo "[$NAME] out=$OUT"
  echo "============================================================"

  # Use chunk-size 2000 (our current default). Skip rerank (we already know it loses).
  uv run python tests/bench/bench_real_corpus.py \
    --corpus "$CORPUS" \
    --golden "$GOLDEN" \
    --modes keyword,hybrid \
    --chunk-size 2000 \
    --embed-model "$MODEL" \
    --embed-dim "$DIM" \
    --out "$OUT" \
    2>&1 | tee "$OUTDIR/${NAME}.log" || {
      echo "[$NAME] FAILED — continuing"
      echo '{"error": "run failed"}' > "$OUT"
    }
done

echo ""
echo "============================================================"
echo "SUMMARY"
echo "============================================================"
python3 - <<PY
import json, pathlib
rows = []
for f in sorted(pathlib.Path("$OUTDIR").glob("*.json")):
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f"{f.stem}: parse error {e}")
        continue
    if "error" in d:
        rows.append((f.stem, "FAILED", "-", "-", "-"))
        continue
    # Expect schema from bench_real_corpus: results[{mode, ndcg_at_10, hit_at_5, mrr_at_10, p95_ms}]
    for r in d.get("results", []):
        mode = r.get("mode", "?")
        rows.append((f.stem, mode, r.get("ndcg_at_10"), r.get("hit_at_5"), r.get("mrr_at_10")))
print(f"{'model':<16}{'mode':<16}{'nDCG@10':<10}{'Hit@5':<10}{'MRR@10':<10}")
print("-" * 62)
for model, mode, ndcg, hit, mrr in rows:
    def fmt(v):
        return f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
    print(f"{model:<16}{mode:<16}{fmt(ndcg):<10}{fmt(hit):<10}{fmt(mrr):<10}")
print(f"\nRaw results: $OUTDIR/")
PY
