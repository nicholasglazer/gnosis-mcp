# GIF Demo Script

Record with [VHS](https://github.com/charmbracelet/vhs) or [asciinema](https://asciinema.org) + [agg](https://github.com/asciinema/agg).

Recommended: VHS (produces GIF directly, deterministic timing, looks great on GitHub).

## Prerequisites

- PostgreSQL running locally (or Docker: `docker run -p 5432:5432 -e POSTGRES_PASSWORD=demo pgvector/pgvector`)
- gnosis-mcp installed: `pip install gnosis-mcp`
- A few sample markdown files in `./sample-docs/`
- `GNOSIS_MCP_DATABASE_URL` exported

## Terminal Commands (copy-paste these)

```bash
# 1. Show version (proves it's installed)
gnosis-mcp --version

# 2. Create tables (fast, idempotent)
gnosis-mcp init-db

# 3. Ingest sample docs
gnosis-mcp ingest ./sample-docs/

# 4. Check stats
gnosis-mcp stats

# 5. Search (keyword)
gnosis-mcp search "authentication"

# 6. Search (hybrid with embeddings, if configured)
gnosis-mcp search "how does login work" --embed

# 7. Verify everything
gnosis-mcp check
```

## Sample Docs to Create

Create `sample-docs/` with 3-4 files before recording:

**sample-docs/getting-started.md:**
```markdown
---
category: guides
---
# Getting Started

## Installation

Install the package with pip and configure your database connection.

## Configuration

Set GNOSIS_MCP_DATABASE_URL to your PostgreSQL connection string.
All other settings have sensible defaults.
```

**sample-docs/authentication.md:**
```markdown
---
category: architecture
---
# Authentication

## Overview

The platform uses JWT tokens for API authentication and session cookies for the dashboard.

## Login Flow

Users authenticate via email/password or OAuth providers. The server validates credentials,
issues a JWT with a 24-hour expiry, and sets an HTTP-only refresh token cookie.

## API Keys

Service-to-service communication uses API keys stored in the database.
Keys are hashed with bcrypt before storage.
```

**sample-docs/billing.md:**
```markdown
---
category: guides
---
# Billing

## Overview

All charges happen before service delivery. Credits are deducted atomically using a database function.

## Credit System

Workspaces purchase credit packs via Stripe. Each AI operation has a defined credit cost.
The billing function checks balance, deducts credits, and returns success/failure in one transaction.

## Webhooks

Stripe webhooks update the workspace credit balance after successful payments.
Failed payments trigger a 3-day grace period before service suspension.
```

## VHS Tape File (recommended)

Save as `demo.tape`:

```vhs
Output demo.gif
Set FontSize 16
Set Width 900
Set Height 500
Set Theme "Catppuccin Mocha"
Set Padding 20

Type "# Gnosis MCP - docs for your AI agent"
Enter
Sleep 1s

Type "gnosis-mcp --version"
Enter
Sleep 1.5s

Type "gnosis-mcp init-db"
Enter
Sleep 2s

Type "gnosis-mcp ingest ./sample-docs/"
Enter
Sleep 2.5s

Type "gnosis-mcp stats"
Enter
Sleep 2s

Type 'gnosis-mcp search "how does login work"'
Enter
Sleep 3s

Type "gnosis-mcp check"
Enter
Sleep 2s

Type "# Ready! Add to your MCP client config and go."
Enter
Sleep 2s
```

Run with: `vhs demo.tape`

## Asciinema Alternative

```bash
# Record
asciinema rec demo.cast

# Run the commands above manually

# Stop recording
exit

# Convert to GIF
agg demo.cast demo.gif --theme monokai --font-size 16
```

## Tips for a Great GIF

1. **Keep it under 30 seconds** -- attention span is short
2. **Use a clean terminal** -- clear history, short prompt (`$ `)
3. **Pause after each output** -- let viewers read the results
4. **Dark theme** -- looks better on GitHub's white background
5. **16px+ font** -- readable on small screens
6. **No scroll** -- keep output concise, fewer docs = cleaner demo
7. **Add to README** -- right after the tagline, before "Why?"

## Where to Put the GIF in README

```markdown
<div align="center">
<h1>Gnosis MCP</h1>
<p><strong>Serve your PostgreSQL docs to AI agents over MCP.</strong></p>

<!-- ADD GIF HERE -->
<img src="demo.gif" alt="Gnosis MCP demo" width="700">

<p>badges...</p>
</div>
```
