#!/usr/bin/env bash
# Stage the directory that .internal/demo-source/hero.tape runs against.
# Run this once before `vhs .internal/demo-source/hero.tape`.
#
#   bash .internal/demo-source/stage-demo.sh
#   vhs .internal/demo-source/hero.tape

set -euo pipefail

# Walk up two levels: .internal/demo-source/ → .internal/ → repo root
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE=/tmp/gnosis-demo-stage

mkdir -p "$STAGE/docs" "$STAGE/bin"

# Demo-only wrapper that filters one repeated INFO banner ("gnosis-mcp started: ...")
# from stderr so the recording stays uncluttered. Real CLI behavior is unchanged.
cat > "$STAGE/bin/gnosis-mcp" <<'WRAPPER'
#!/usr/bin/env bash
exec /home/ng/prod/gnosis-mcp/.venv/bin/gnosis-mcp "$@" 2> >(grep -v "gnosis-mcp started:" >&2)
WRAPPER
chmod +x "$STAGE/bin/gnosis-mcp"
# Small representative slice. 6 docs → ~90 chunks → clean stats output.
cp "$REPO/docs/config.md" \
   "$REPO/docs/tools.md" \
   "$REPO/docs/cli.md" \
   "$REPO/docs/rest-api.md" \
   "$REPO/docs/benchmarks.md" \
   "$REPO/README.md" \
   "$STAGE/docs/"

# Pre-touch the DB path so the first init-db inside the tape is deterministic.
: > "$STAGE/docs.db" 2>/dev/null || true
rm -f "$STAGE/docs.db"

echo "staged: $STAGE"
ls -la "$STAGE/docs/"
