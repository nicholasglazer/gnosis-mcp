---
name: setup
description: First-time setup wizard for Gnosis MCP. Install, init the database, ingest a docs folder, wire your editor — in that order.
---

# Setup

Gets you from nothing to "agent searching my docs" in 60 seconds.

## Usage

```
/gnosis:setup                      # Interactive — asks where your docs live
/gnosis:setup /path/to/docs        # Same, but ingest that folder right away
/gnosis:setup --postgres           # Print PostgreSQL setup instructions too
```

## Target: $ARGUMENTS

---

## Step 1 — Install

Pick the extras you need. They're additive.

```bash
pip install gnosis-mcp                        # core (SQLite, keyword search)
pip install 'gnosis-mcp[embeddings]'          # + local ONNX embeddings (hybrid search)
pip install 'gnosis-mcp[web]'                 # + web crawler (sitemap / BFS)
pip install 'gnosis-mcp[postgres]'            # + PostgreSQL backend
pip install 'gnosis-mcp[rst,pdf]'             # + .rst and .pdf file ingestion
pip install 'gnosis-mcp[reranking]'           # + cross-encoder reranker
                                              #   (OFF by default; tune before turning on —
                                              #    the bundled MS-MARCO model can HURT
                                              #    dev-doc retrieval by ~27 nDCG@10)
```

Full stack in one shot:

```bash
pip install 'gnosis-mcp[embeddings,web,postgres,rst,pdf]'
```

Verify:

```bash
gnosis-mcp --version     # should print the semver (≥ 0.10.13)
```

---

## Step 2 — Pick a backend (usually SQLite)

**SQLite (default):** zero config. Database auto-creates at
`~/.local/share/gnosis-mcp/docs.db`. Great up to ~100 k chunks.

**PostgreSQL:** use when you have multiple concurrent writers, need a
shared index across machines, or corpus > 100 k chunks.

```bash
# Postgres (only if you need it)
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
```

Check that pgvector is available on the server:

```bash
psql "$GNOSIS_MCP_DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## Step 3 — Initialise the database

Idempotent. Safe to run any time.

```bash
gnosis-mcp init-db
```

---

## Step 4 — Ingest your docs

If `$ARGUMENTS` includes a path, use it. Otherwise ask the user where
their docs live.

```bash
# Preview (dry-run): lists files that would be ingested
gnosis-mcp ingest /path/to/docs --dry-run

# Real ingest, with embeddings for hybrid search
gnosis-mcp ingest /path/to/docs --embed
```

**Default chunk size is 2000 characters** (peak of the v0.11 sweep on
real dev-docs). Tune it for your corpus with `/gnosis:tune` after
you've got some real queries to score against.

Watch mode — auto re-ingests on file changes, no cron needed:

```bash
gnosis-mcp serve --watch /path/to/docs --transport streamable-http --rest
```

---

## Step 5 — Verify

```bash
gnosis-mcp check     # DB connectivity + schema sanity
gnosis-mcp stats     # doc / chunk / embedding counts
```

Expect something like:

```
Backend:       sqlite
Version:       SQLite 3.46.0
chunks_table:  ✓ (1,742 rows)
fts_table:     ✓
sqlite_vec:    ✓ (1,742 vectors)
links_table:   ✓ (812 rows)
```

If anything says `✗`, run `/gnosis:status` for diagnosis.

---

## Step 6 — Wire your editor

Pick one. Each config goes in the project root (or global config — see
each editor's docs).

### Claude Code — `.claude/mcp.json` or `~/.claude/mcp.json`

```json
{
  "mcpServers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

For shared-state setups (agent teams, parallel tabs) — use HTTP:

```json
{
  "mcpServers": {
    "gnosis": {
      "type": "url",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Start the server separately:

```bash
gnosis-mcp serve --transport streamable-http --rest --watch ./docs
```

### Cursor — `.cursor/mcp.json`

Same shape as Claude Code. Drop the JSON above.

### Windsurf — `~/.codeium/windsurf/mcp_config.json`

Same shape.

### VS Code (GitHub Copilot) — `.vscode/mcp.json`

Key is `"servers"`, not `"mcpServers"`:

```json
{
  "servers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

### JetBrains — Settings → Tools → AI Assistant → MCP Servers

Command: `gnosis-mcp`, args: `serve`.

### Cline — Cline's MCP panel in the sidebar

Command: `gnosis-mcp`, args: `["serve"]`.

Full per-editor guidance (including auth, env vars for write mode, and
team / remote setups) lives in
[llms-install.md](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md).

---

## Step 7 — Report

Print a compact summary to the user:

```
## Setup complete

| Setting           | Value |
|-------------------|-------|
| Backend           | sqlite |
| Database          | ~/.local/share/gnosis-mcp/docs.db |
| Documents         | 42 |
| Chunks            | 170 |
| Embeddings        | 170 / 170 (100 %) |
| Chunk size        | 2000 chars (default) |
| Writable          | false (set GNOSIS_MCP_WRITABLE=true to enable upsert/delete) |

Next:
  /gnosis:search "your first query"   — sanity check retrieval works
  /gnosis:tune                         — find your chunk-size optimum (optional)
  /gnosis:ingest git <repo>            — index commit history too (optional)
```

---

## Optional — extras

### Git history

```bash
gnosis-mcp ingest-git . --since 6m --embed
```

### Web crawl (vendor docs → local index)

```bash
gnosis-mcp crawl https://docs.stripe.com --sitemap --embed
```

### Writes from your agent

Off by default for safety. Enable only if you want your agent to call
`upsert_doc` / `delete_doc`:

```bash
export GNOSIS_MCP_WRITABLE=true
```

### REST API on the same port

```bash
gnosis-mcp serve --transport streamable-http --rest
```

Then: `curl http://127.0.0.1:8000/api/search?q=auth&limit=5`.

Add Bearer auth for any non-localhost exposure:

```bash
export GNOSIS_MCP_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

---

## Notes

- **Re-running ingest is cheap** — content hashes skip unchanged files
- **Watch mode beats cron** — mtime polling + debounce, no fsnotify dep
- **Rerankers are off by default**: they help in some domains, hurt in
  others. Run `/gnosis:tune full` to find out which applies to your
  corpus before enabling
- **PostgreSQL is a drop-in swap**: set `GNOSIS_MCP_DATABASE_URL` and
  re-run `init-db` + `ingest`. Same tool API.
