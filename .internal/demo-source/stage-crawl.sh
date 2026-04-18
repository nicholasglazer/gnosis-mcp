#!/usr/bin/env bash
# Stage a local mock "vendor docs" HTTP server that the crawl demo tape
# points at. Fake-Stripe-flavoured pages + a sitemap + robots.txt — enough
# that `gnosis-mcp crawl --sitemap` exercises every real code path
# (robots check, sitemap parse, HTML fetch, trafilatura extract, chunking)
# without hitting the actual network.
#
# Lifecycle:
#   - spawns a Python http.server on :8765 in the background
#   - pid written to /tmp/gnosis-demo-crawl/server.pid
#   - auto-kills any prior instance before starting fresh
#
# Server stays up after this script exits — the tape runs against it.
# Clean up with: kill $(cat /tmp/gnosis-demo-crawl/server.pid)

set -euo pipefail

STAGE=/tmp/gnosis-demo-crawl
PORT=8765
mkdir -p "$STAGE/bin" "$STAGE/www/docs/payments" "$STAGE/www/docs/billing" "$STAGE/www/docs/webhooks"

# Kill prior server if still around.
if [[ -f "$STAGE/server.pid" ]]; then
  kill "$(cat "$STAGE/server.pid")" 2>/dev/null || true
  rm -f "$STAGE/server.pid"
fi

# ── Mock content: 5 pages that look like realistic vendor docs ────────────
cat > "$STAGE/www/robots.txt" <<'EOF'
User-agent: *
Allow: /docs/
Disallow: /admin/
Sitemap: http://localhost:8765/sitemap.xml
EOF

cat > "$STAGE/www/sitemap.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://localhost:8765/docs/payments/charges.html</loc></url>
  <url><loc>http://localhost:8765/docs/payments/refunds.html</loc></url>
  <url><loc>http://localhost:8765/docs/billing/subscriptions.html</loc></url>
  <url><loc>http://localhost:8765/docs/webhooks/idempotency.html</loc></url>
  <url><loc>http://localhost:8765/docs/webhooks/signing.html</loc></url>
</urlset>
EOF

cat > "$STAGE/www/docs/payments/charges.html" <<'EOF'
<!DOCTYPE html><html><head><title>Creating a charge</title></head><body>
<h1>Creating a charge</h1>
<p>To charge a card, create a PaymentIntent with an amount in the smallest currency unit.
Attach a payment method and confirm the intent. The charge is recorded once the intent
transitions to <code>succeeded</code>.</p>
<h2>Test cards</h2>
<p>Use <code>4242 4242 4242 4242</code> in test mode. Any future expiry and any CVC.</p>
</body></html>
EOF

cat > "$STAGE/www/docs/payments/refunds.html" <<'EOF'
<!DOCTYPE html><html><head><title>Refunds</title></head><body>
<h1>Refunds</h1>
<p>Refund a captured charge by calling the refund endpoint with the charge ID.
Full refunds reverse the entire amount; partial refunds specify the amount explicitly.</p>
<p>Refunds are processed asynchronously and may take 5-10 business days to appear on
the customer's statement.</p>
</body></html>
EOF

cat > "$STAGE/www/docs/billing/subscriptions.html" <<'EOF'
<!DOCTYPE html><html><head><title>Subscriptions</title></head><body>
<h1>Subscriptions</h1>
<p>Subscriptions bill a customer on a recurring schedule. Attach a price to a customer
to start a subscription. Proration applies when upgrading or downgrading mid-cycle.</p>
<h2>Lifecycle hooks</h2>
<p>The <code>customer.subscription.updated</code> webhook fires on every state change.</p>
</body></html>
EOF

cat > "$STAGE/www/docs/webhooks/idempotency.html" <<'EOF'
<!DOCTYPE html><html><head><title>Idempotency</title></head><body>
<h1>Idempotency</h1>
<p>All write endpoints accept an <code>Idempotency-Key</code> header. Re-issuing the same
key within 24 hours returns the cached response instead of creating a duplicate resource.
This is essential for safe retries after network failures.</p>
<h2>Generating keys</h2>
<p>Use a UUID v4 per logical operation. Never reuse keys across different payloads.</p>
</body></html>
EOF

cat > "$STAGE/www/docs/webhooks/signing.html" <<'EOF'
<!DOCTYPE html><html><head><title>Webhook signing</title></head><body>
<h1>Webhook signing</h1>
<p>Every webhook request includes a <code>Signature</code> header. Verify it with your
endpoint signing secret before trusting the payload. Reject requests older than 5 minutes
to block replay attacks.</p>
</body></html>
EOF

# ── Demo-only wrapper: filters the repeated startup banner and the
# noisy per-request httpx INFO lines. Real CLI behaviour is unchanged.
cat > "$STAGE/bin/gnosis-mcp" <<'WRAPPER'
#!/usr/bin/env bash
exec /home/ng/prod/gnosis-mcp/.venv/bin/gnosis-mcp "$@" \
  2> >(grep -vE "gnosis-mcp started:|^httpx: HTTP Request:" >&2)
WRAPPER
chmod +x "$STAGE/bin/gnosis-mcp"

# Wipe the persistent crawl cache so the demo always starts fresh.
rm -f "$HOME/.local/share/gnosis-mcp/crawl-cache.json"

# ── Start the HTTP server in background ──────────────────────────────────
cd "$STAGE/www"
python3 -m http.server "$PORT" > "$STAGE/server.log" 2>&1 &
echo $! > "$STAGE/server.pid"
cd - >/dev/null

# Give the server a moment to bind.
sleep 0.8
if ! curl -sf "http://localhost:$PORT/robots.txt" > /dev/null; then
  echo "ERROR: mock server didn't bind on :$PORT — see $STAGE/server.log" >&2
  exit 1
fi

echo "staged: $STAGE"
echo "server: http://localhost:$PORT (pid $(cat "$STAGE/server.pid"))"
echo "stop with: kill \$(cat $STAGE/server.pid)"
