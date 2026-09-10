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

## The procedure lives in one place

**[llms-install.md](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md)
is the install procedure.** Follow its
[agent checklist](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md#agent-checklist)
in order instead of re-deriving the steps here:

1. Install the package — `pip install 'gnosis-mcp[embeddings,web]'`, or `uv tool install` when the
   machine has no suitable Python.
2. `gnosis-mcp init-db` — creates the schema; idempotent.
3. `gnosis-mcp check` — must print `FTS5: ready` and exit 0. **If FTS5 is missing, stop and tell the
   user** rather than ingesting: keyword search cannot work on that Python build.
4. `gnosis-mcp ingest <path> --dry-run` to preview, then `gnosis-mcp ingest <path> --embed`.
5. `gnosis-mcp search "<a query you know the answer to>"` — the first real verification.

Backend choice (SQLite by default; PostgreSQL for concurrent writers or > 100 k chunks), extras,
flags, write mode, and the platform notes (Windows `.exe` paths, WSL2, remote HTTP transport) are in
that file. If this skill and llms-install.md ever disagree, llms-install.md wins.

## Claude Code extras — plugin, agents, skills

Search works with the MCP server alone; the extras are 5 subagents, 8 slash commands and a
session-start hook. Two ways in:

- **Plugin (Path A)** — `claude plugin marketplace add nicholasglazer/gnosis-mcp`, then
  `claude plugin install gnosis`, then restart Claude Code.
- **Manual copy (Path B)** — clone the repo and copy the agents and skills you want into
  `.claude/agents/` and `.claude/skills/` in your project. Exact commands, and how to cherry-pick a
  subset, are in
  [Path B](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md#path-b--manual-copy-paste).

Say which route the user took when you report — the manual route installs a subset.

---

## Wire your editor

Each config goes in the project root (or the editor's global config — see each editor's docs).

### Claude Code — `.mcp.json` in the project root, or `claude mcp add --scope user`

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

For shared-state setups (agent teams, parallel tabs) — one server, many clients — use HTTP:

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

Other editors — Cursor (`.cursor/mcp.json`), Windsurf, VS Code (`.vscode/mcp.json`, key
`"servers"`), Zed (`context_servers`), opencode, JetBrains, Cline — have copy-paste configs in
[Path C](https://github.com/nicholasglazer/gnosis-mcp/blob/main/llms-install.md#path-c--mcp-server-only-any-editor).

---

## Report

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

If any step failed, report that instead of a success table. Anything from the checklist above that
went wrong: `/gnosis:status` diagnoses connectivity and schema; failure modes are catalogued in
[docs/troubleshooting.md](https://github.com/nicholasglazer/gnosis-mcp/blob/main/docs/troubleshooting.md).

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

### Watch mode (no cron needed)

```bash
gnosis-mcp serve --watch /path/to/docs --transport streamable-http --rest
```

### Writes from your agent

Off by default for safety. Enable only if you want your agent to call
`upsert_doc` / `delete_doc` / `update_metadata`:

```bash
export GNOSIS_MCP_WRITABLE=true
```

### PostgreSQL

```bash
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
psql "$GNOSIS_MCP_DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"   # hybrid search
gnosis-mcp init-db && gnosis-mcp ingest /path/to/docs --embed
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
- **Chunk size defaults to 2000 characters** (peak of the v0.11 sweep on real
  dev-docs). Tune it against your own queries with `/gnosis:tune`
- **Rerankers are off by default**: they help in some domains, hurt in
  others. Run `/gnosis:tune full` to find out which applies to your
  corpus before enabling
- **PostgreSQL is a drop-in swap**: set `GNOSIS_MCP_DATABASE_URL` and
  re-run `init-db` + `ingest`. Same tool API.
