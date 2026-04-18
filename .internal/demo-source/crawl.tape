# gnosis-mcp — crawl demo tape.
#
#   bash .internal/demo-source/stage-crawl.sh      # starts a local mock Stripe-docs server
#   vhs .internal/demo-source/crawl.tape           # renders demo/demo-crawl.gif
#   (server stops itself when the tape exits)
#
# Story: crawl a vendor docs site, then search it locally.
#   1. crawl --sitemap --dry-run (plan: see what would be fetched)
#   2. crawl --sitemap (real fetch, uses ETag cache)
#   3. stats (see it landed in our SQLite index)
#   4. search "idempotency" (find what we actually crawled)

Output demo/demo-crawl.gif

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
Set Framerate 20

Hide
Type "export PS1='$ '"
Enter
Type "cd /tmp/gnosis-demo-crawl"
Enter
Type "export GNOSIS_MCP_DATABASE_URL=sqlite:///tmp/gnosis-demo-crawl/docs.db"
Enter
Type "export GNOSIS_MCP_LOG_LEVEL=INFO"
Enter
# Demo only: crawl localhost. Real-world crawls use public URLs and this flag is off.
Type "export GNOSIS_MCP_ALLOW_PRIVATE_CRAWL=true"
Enter
Type "export PATH=/tmp/gnosis-demo-crawl/bin:$PATH"
Enter
Type "rm -f docs.db && gnosis-mcp init-db > /dev/null 2>&1"
Enter
Type "clear"
Enter
Show

# ── 1. see what a crawl would do before committing ──────────────────────
Type "# Crawl a vendor docs site — planning pass first."
Sleep 1200ms
Enter
Type "gnosis-mcp crawl http://localhost:8765 --sitemap --dry-run"
Sleep 400ms
Enter
Sleep 3000ms

# ── 2. real crawl, writes into local SQLite ──────────────────────────────
Type "# Fetch for real. robots.txt respected; ETag cache kicks in on re-runs."
Sleep 1200ms
Enter
Type "gnosis-mcp crawl http://localhost:8765 --sitemap"
Sleep 400ms
Enter
Sleep 4000ms

# ── 3. confirm it landed ─────────────────────────────────────────────────
Type "# See what landed in the local index."
Sleep 1000ms
Enter
Type "gnosis-mcp stats"
Sleep 400ms
Enter
Sleep 2800ms

# ── 4. search the crawled content ────────────────────────────────────────
Type "# Search the crawled docs — same API, same index."
Sleep 1000ms
Enter
Type "gnosis-mcp search 'idempotency key' --limit 2"
Sleep 400ms
Enter
Sleep 3500ms

# ── Outro ────────────────────────────────────────────────────────────────
Hide
Type "clear"
Enter
Show
Type "# gnosis-mcp crawl — any site, your local index"
Sleep 500ms
Enter
Type "# github.com/nicholasglazer/gnosis-mcp  ·  gnosismcp.com"
Sleep 2000ms
Enter
Sleep 800ms
