# gnosis-mcp — hero demo tape for VHS.
#
#   vhs demo/hero.tape        # produces ../demo-hero.gif
#
# Story in 45 s:
#   1. pip install
#   2. ingest ./docs (real gnosis-mcp docs)
#   3. stats
#   4. hybrid search
#   5. serve + /health probe (REST mirror)
#   6. upsert a new doc via curl → re-search finds it

Output demo-hero.gif
Set Width 1240
Set Height 720
Set FontSize 15
Set FontFamily "JetBrainsMono Nerd Font"
Set Theme "Catppuccin Mocha"
Set Shell "bash"
Set TypingSpeed 55ms
Set Padding 24
Set Margin 8
Set MarginFill "#1e1e2e"
Set BorderRadius 8

# Clean shell
Hide
Type "export PS1='$ '"
Enter
Type "clear"
Enter
Show

# ── 1. install (already installed; we show the command for the viewer) ───
Type "# Self-hosted docs search for AI agents. Zero config."
Sleep 1s
Enter
Type "pip install 'gnosis-mcp[embeddings,web]'"
Sleep 500ms
Enter
Sleep 800ms
Hide
Type "echo 'Successfully installed gnosis-mcp-0.10.13'"
Enter
Show
Sleep 1500ms
Enter

# ── 2. ingest ─────────────────────────────────────────────────────────────
Type "gnosis-mcp ingest ./docs --embed"
Sleep 500ms
Enter
Sleep 2500ms

# ── 3. stats ──────────────────────────────────────────────────────────────
Type "gnosis-mcp stats"
Sleep 400ms
Enter
Sleep 2500ms

# ── 4. hybrid search ──────────────────────────────────────────────────────
Type "gnosis-mcp search 'how do i switch from sqlite to postgres' --embed"
Sleep 400ms
Enter
Sleep 3500ms

# ── 5. serve + REST mirror ────────────────────────────────────────────────
Type "gnosis-mcp serve --transport streamable-http --rest &"
Sleep 400ms
Enter
Sleep 2500ms

Type "curl -s localhost:8000/health | jq ."
Sleep 400ms
Enter
Sleep 2000ms

# ── 6. write + search through REST ────────────────────────────────────────
Type "curl -s 'localhost:8000/api/search?q=hybrid%20RRF&limit=3' | jq '.hits[0:2]'"
Sleep 400ms
Enter
Sleep 3000ms

# ── Outro ─────────────────────────────────────────────────────────────────
Hide
Type "kill %1 2>/dev/null; clear"
Enter
Show
Type "# gnosis-mcp — MCP-native, SQLite default, hybrid search"
Sleep 400ms
Enter
Type "# github.com/nicholasglazer/gnosis-mcp  ·  gnosismcp.com"
Sleep 2s
Enter
Sleep 800ms
