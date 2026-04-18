# gnosis-mcp — hero demo tape for VHS.
#
#   # Staging must exist first (real commands, no fakes):
#   bash .internal/demo-source/stage-demo.sh
#
#   # Then render (from repo root, so `Output demo/demo-hero.gif` resolves):
#   cd /home/ng/prod/gnosis-mcp && vhs .internal/demo-source/hero.tape
#
# Produces demo/demo-hero.gif (target: under 1 MB after post-process).
#
# Story in ~25 s — real commands only, no fake echo injection:
#   1. show version
#   2. ingest a small staged docs slice
#   3. stats
#   4. search
#   5. outro

Output demo/demo-hero.gif

# 960×540 keeps the GIF under our 1 MB budget with 64-color palette.
Set Width 960
Set Height 540
Set FontSize 14
Set FontFamily "JetBrains Mono"
Set Theme "Catppuccin Mocha"
Set Shell "bash"
Set TypingSpeed 45ms
Set Padding 20
Set Margin 8
Set MarginFill "#1e1e2e"
Set BorderRadius 6
# Drop framerate for a smaller file — terminal demos don't need 60fps.
Set Framerate 20
Set PlaybackSpeed 1.0

# Clean shell — hidden setup so the viewer sees a pristine prompt.
Hide
Type "export PS1='$ '"
Enter
Type "cd /tmp/gnosis-demo-stage"
Enter
Type "export GNOSIS_MCP_DATABASE_URL=sqlite:///tmp/gnosis-demo-stage/docs.db"
Enter
# Keep INFO level so `ingest` shows its per-file progress. The single-line
# "gnosis-mcp started: backend=sqlite ..." banner is informative, not noise.
Type "export GNOSIS_MCP_LOG_LEVEL=INFO"
Enter
# Put the demo wrapper first on PATH (staged by demo/stage-demo.sh). The wrapper
# filters one INFO-level startup banner so repeated invocations look clean.
Type "export PATH=/tmp/gnosis-demo-stage/bin:$PATH"
Enter
# Fresh DB every render.
Type "rm -f docs.db && gnosis-mcp init-db > /dev/null 2>&1"
Enter
Type "clear"
Enter
Show

# ── 1. what we're looking at ──────────────────────────────────────────
Type "# Self-hosted docs search for AI agents. Zero config, SQLite default."
Sleep 1500ms
Enter
Type "gnosis-mcp --version"
Sleep 300ms
Enter
Sleep 1500ms

# ── 2. ingest ─────────────────────────────────────────────────────────
Type "# Ingest a folder of markdown docs."
Sleep 800ms
Enter
Type "gnosis-mcp ingest ./docs"
Sleep 300ms
Enter
Sleep 2500ms

# ── 3. stats ──────────────────────────────────────────────────────────
Type "# Confirm what landed in the index."
Sleep 800ms
Enter
Type "gnosis-mcp stats"
Sleep 300ms
Enter
Sleep 2800ms

# ── 4. search ─────────────────────────────────────────────────────────
Type "# Search — keyword FTS5 + BM25 scoring."
Sleep 800ms
Enter
Type "gnosis-mcp search 'hybrid search' --limit 2"
Sleep 300ms
Enter
Sleep 3200ms

# ── Outro ─────────────────────────────────────────────────────────────
Hide
Type "clear"
Enter
Show
Type "# gnosis-mcp — MCP-native · SQLite default · hybrid search"
Sleep 500ms
Enter
Type "# github.com/nicholasglazer/gnosis-mcp  ·  gnosismcp.com"
Sleep 2000ms
Enter
Sleep 800ms
