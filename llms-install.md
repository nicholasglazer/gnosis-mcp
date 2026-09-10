# Gnosis MCP — Installation Guide

Three install paths, pick the one that matches how you work:

| You want… | Path | Effort |
|---|---|---|
| **Plugin for Claude Code** — agents, skills, hooks, and the MCP server auto-wired | Path A (plugin marketplace) | One command |
| **Manual control** — cherry-pick which agents/skills land in your config, edit them first | Path B (copy-paste) | ~5 minutes |
| **Just the MCP server** — you don't use Claude Code or don't want the plugin extras | Path C (MCP-only) | Per-editor JSON snippet |

All three paths install the same underlying `gnosis-mcp` Python package. The difference is what wires up around it.

## Agent checklist

*For an AI agent installing gnosis-mcp on a user's behalf.* Work these in order — each step says how
to verify it and what to do when it fails. The prose below is the same procedure written for humans;
[Path C](#path-c--mcp-server-only-any-editor) is the closest match.

1. **Confirm the target.** Ask which folder of docs to index, and whether the user wants the Claude
   Code extras ([Path A](#path-a--claude-code-plugin-recommended) or
   [Path B](#path-b--manual-copy-paste)) or only the MCP server
   ([Path C](#path-c--mcp-server-only-any-editor)). Don't guess the docs path.
2. **Install.** Python 3.11 or later (`python --version`).

   ```bash
   pip install 'gnosis-mcp[embeddings,web]'
   # or, when the machine has no suitable Python:
   uv tool install 'gnosis-mcp[embeddings,web]'
   ```

   *Verify:* `gnosis-mcp --version` prints a version. *If it fails:* no Python 3.11+ — install
   [uv](https://docs.astral.sh/uv/) and use the `uv tool install` form; on Windows see
   [Platforms](#platforms) for the `.exe` path.
3. **Check that SQLite has FTS5 — before ingesting.** Keyword search needs SQLite **FTS5**, which is
   compiled into the Python build rather than guaranteed by it. Run this with the same Python that
   runs `gnosis-mcp`:

   ```bash
   python -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"
   ```

   Exit 0 = FTS5 is present. `no such module: fts5` = it is not — **stop and tell the user**, because
   every later step would appear to succeed while search returns nothing. Fix the Python (python.org
   installer, `uv python install`) or use PostgreSQL instead.
4. **Initialise the database.** `gnosis-mcp init-db` (idempotent). *Verify:* `gnosis-mcp check`
   prints `FTS5: ready` and ends with `Result: healthy (exit 0)` — the exit code is the gate. A
   non-zero exit here is a stop condition, not a warning.
5. **Ingest.** `gnosis-mcp ingest <path> --dry-run` to preview, then
   `gnosis-mcp ingest <path> --embed`. *Verify:* `gnosis-mcp stats` reports a non-zero
   Documents / Chunks count.
6. **Prove retrieval works.** `gnosis-mcp search "<a phrase you know is in the docs>"` must return
   hits. If it returns nothing, the user's agent will find nothing either — fix that before wiring a
   client.
7. **Wire the client.** Add the stdio entry for the user's client
   ([Path C](#path-c--mcp-server-only-any-editor)); on Windows use the full path to
   `gnosis-mcp.exe` ([Platforms](#platforms)). A read-only client sees six tools — write tools are
   advertised only with `GNOSIS_MCP_WRITABLE=true`.
8. **Report.** Docs path, database path, backend, doc/chunk counts, the client config file you
   wrote, and anything you skipped. If a step failed, report the failure instead of continuing or
   claiming success.

Failures at any step: [`docs/troubleshooting.md`](docs/troubleshooting.md). Never report "setup
complete" without the `check` and `search` output to back it.

## Any other MCP client

Claude Code is not required. Any MCP client works — install the package, index your docs, then add this stdio entry to the client's config:

```bash
pip install gnosis-mcp
gnosis-mcp ingest ./docs/
```

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

Config file location, and the clients that use a different key than `mcpServers`, are in [Path C](#path-c--mcp-server-only-any-editor) below.

## Prerequisites

- Python 3.11 or later
- A folder of markdown files you want your AI agent to search

No database server required — SQLite works out of the box.

---

## Platforms

| Platform | Install | Database | Notes |
|---|---|---|---|
| **Linux / macOS** | `pip install 'gnosis-mcp[embeddings,web]'`, or `uv tool install` | `~/.local/share/gnosis-mcp/docs.db` | Docker, systemd and the reverse-proxy recipes in [`docs/deployment.md`](docs/deployment.md) assume Linux. |
| **Windows (native)** | `winget install astral-sh.uv`, then `uv tool install 'gnosis-mcp[embeddings,web]'` — plain `pip install` works too | `%USERPROFILE%\.local\share\gnosis-mcp\docs.db` | Before ingesting, run the FTS5 probe from [step 3](#agent-checklist) of the checklist: keyword search needs SQLite **FTS5**, which is compiled into the Python build rather than guaranteed by it. `pip`/`uv` install console scripts as `.exe` shims under `%USERPROFILE%\.local\bin`, so point your MCP client at the full path to `gnosis-mcp.exe` instead of relying on PATH inheritance. |
| **Windows via WSL2** | Same as Linux, inside WSL | Inside the WSL filesystem | The simplest route to Docker or systemd from Windows — localhost forwarding means a Windows client reaches `http://127.0.0.1:8000/mcp`. Index docs that live in the Linux filesystem. |
| **Remote server / VM** | Same as Linux, on the host | On the host | Serve over HTTP and connect to the host's address (below). Set `GNOSIS_MCP_API_KEY` whenever the network is not trusted. |

### Windows: worked MCP server entry

Stdio, with the full path to the `.exe` (backslashes doubled for JSON):

```json
{
  "mcpServers": {
    "gnosis": {
      "command": "C:\\Users\\you\\.local\\bin\\gnosis-mcp.exe",
      "args": ["serve"]
    }
  }
}
```

### Remote / WSL / VM: HTTP transport

Start the server on the machine that holds the database:

```bash
gnosis-mcp serve --transport streamable-http --host 0.0.0.0 --port 8000
```

Then point the client at it — `127.0.0.1` from a Windows client under WSL2 (localhost forwarding),
or the host's address from anywhere else:

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

Set `GNOSIS_MCP_API_KEY` on the server for any non-loopback exposure — see the security checklist in
[`docs/deployment.md`](docs/deployment.md).

---

## Path A — Claude Code plugin (recommended)

If you use Claude Code, this is the one-command install. Gets you the MCP server **plus** 5 subagents, 8 slash commands, and a session-start health check.

```bash
# Install the Python package first
pip install 'gnosis-mcp[embeddings,web]'

# Tell Claude Code about this marketplace, then install the plugin
claude plugin marketplace add nicholasglazer/gnosis-mcp
claude plugin install gnosis

# Index your docs
gnosis-mcp ingest ./docs/ --embed
```

Restart Claude Code. You now have:

| Component | What you get |
|---|---|
| MCP server | `gnosis-mcp serve` — auto-configured, search tools available in every chat |
| `/gnosis:setup` | First-time wizard: install → init-db → ingest → wire your editor |
| `/gnosis:ingest` | Bulk ingest (files, git history, web crawl) + re-ingest + prune |
| `/gnosis:search` | Keyword / hybrid / git-history search, formatted output |
| `/gnosis:manage` | Single-file CRUD (add, delete, update metadata, related) |
| `/gnosis:tune` | Chunk-size sweep against your own golden queries |
| `/gnosis:eval` | Single-shot retrieval quality check with baseline tracking |
| `/gnosis:context` | Usage-weighted topic primer for session startup |
| `/gnosis:status` | Connectivity, schema, corpus health diagnostic |
| 5 agents | `doc-explorer`, `doc-keeper`, `corpus-sync`, `context-loader`, `doc-reviewer` |
| Session hook | Checks DB connectivity on session start — warns loudly if unreachable |

---

## Path B — Manual copy-paste

For users who want to pick specific agents/skills, edit them before installing, or use a non-plugin-capable MCP client.

```bash
# 1. Clone the repo to grab the agents + skills
git clone https://github.com/nicholasglazer/gnosis-mcp /tmp/gnosis-mcp

# 2. Install the Python package
pip install 'gnosis-mcp[embeddings,web]'

# 3. Copy whichever agents + skills you want into your project
mkdir -p .claude/agents .claude/skills
cp /tmp/gnosis-mcp/agents/*.md .claude/agents/           # all 5 — or pick specific ones
cp -r /tmp/gnosis-mcp/skills/* .claude/skills/           # all 8 — or pick specific dirs

# 4. Wire gnosis-mcp as an MCP server
cat > .mcp.json <<'JSON'
{
  "mcpServers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
JSON

# 5. Index your docs
gnosis-mcp ingest ./docs --embed
```

Restart your Claude Code session. The agents and slash commands are available exactly as with Path A, just with whichever subset you chose to copy. Edit the `.md` files to customize prompts for your codebase before (or after) copying.

To remove later: `rm .claude/agents/<name>.md` or `rm -rf .claude/skills/<name>/`.

---

## Path C — MCP server only (any editor)

If you don't use Claude Code, don't want the agent/skill bundle, or want to wire gnosis-mcp as a plain MCP server in a different editor.

### Step 1: Install

```bash
pip install gnosis-mcp
```

Or with uvx (no install needed):

```bash
uvx gnosis-mcp serve
```

For local semantic search (no API key needed, ~23MB model download):

```bash
pip install gnosis-mcp[embeddings]
```

For PostgreSQL support:

```bash
pip install gnosis-mcp[postgres]
```

For web crawling (ingest docs from websites):

```bash
pip install gnosis-mcp[web]
```

### Step 2: Load Your Docs

Point at a folder of markdown files:

```bash
gnosis-mcp ingest ./docs/
```

This auto-creates the SQLite database at `~/.local/share/gnosis-mcp/docs.db` (Unix/macOS) or `%USERPROFILE%\.local\share\gnosis-mcp\docs.db` (Windows), scans all `.md` files, chunks them by H2 headings, extracts metadata from frontmatter, and inserts into the database. Re-running skips unchanged files — safe to run as often as you like.

Override the path with `GNOSIS_MCP_DATABASE_URL=sqlite:///C:/path/to/docs.db` (Windows) or `sqlite:///~/custom/path/docs.db` (Unix).

For PostgreSQL, set the URL first:

```bash
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
gnosis-mcp init-db
gnosis-mcp ingest ./docs/
```

Preview what would be indexed without writing anything:

```bash
gnosis-mcp ingest ./docs/ --dry-run
```

### Step 3: Verify

```bash
gnosis-mcp check    # verify database connection, schema, and FTS5
gnosis-mcp stats    # see document and chunk counts
gnosis-mcp search "getting started"   # test a search
```

`check` is the gate: it exits `0` only when the backend started and the tables the server needs are
present, and it names whatever is missing before exiting `1`. On SQLite it must print
`FTS5: ready` — keyword search needs FTS5, which is compiled into your Python's SQLite rather than
guaranteed by it. On a brand-new database `check` reports the schema as missing until the first
`init-db` (or the first `ingest`, which creates the schema itself); after that, a non-zero exit
means something is actually wrong — [`docs/troubleshooting.md`](docs/troubleshooting.md).

### Step 4: Connect to Your Editor

Add the MCP server config to your editor so your AI agent can search your docs.

**Claude Code** — add to `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

**Claude Desktop** — add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

**Cursor** — add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

**Windsurf** — add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

**VS Code (GitHub Copilot)** — add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

Also discoverable via VS Code MCP gallery — search `@mcp gnosis` in Extensions view.

**Zed** — add to your `settings.json` (`zed: open settings file`). Zed's key is `context_servers`, not `mcpServers`:

```json
{
  "context_servers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

Check the status dot under **Settings → AI → MCP Servers** — green means the server is active.

**opencode** — add to `opencode.json` in your project root (or `~/.config/opencode/opencode.json` for every project). opencode's key is `mcp`, and the command is an array:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "gnosis": {
      "type": "local",
      "command": ["gnosis-mcp", "serve"],
      "enabled": true
    }
  }
}
```

**JetBrains (IntelliJ, PyCharm, WebStorm)** — go to Settings > Tools > AI Assistant > MCP Servers, click +, set command to `gnosis-mcp` and arguments to `serve`.

**Cline** — open the Cline MCP settings panel and add the same server config.

For PostgreSQL, add an `env` block to any of the above (Zed takes the same `env` key; opencode calls it `environment`):

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
      }
    }
  }
}
```

---

## Optional: Enable Write Mode

By default a read-only client sees **six** tools — `search_docs`, `get_doc`, `get_related`,
`search_git_history`, `get_context`, `get_graph_stats`. To let your AI agent create, update, and
delete docs, set `GNOSIS_MCP_WRITABLE=true`, which adds the other three (`upsert_doc`, `delete_doc`,
`update_metadata`) to `tools/list`:

```json
{
  "mcpServers": {
    "docs": {
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_WRITABLE": "true"
      }
    }
  }
}
```

## Optional: Add Semantic Search

Keyword search works immediately. For semantic search (finding docs by meaning, not just keywords):

### SQLite (local ONNX — no API key needed)

1. Install with embeddings: `pip install gnosis-mcp[embeddings]`
2. Ingest with embeddings: `gnosis-mcp ingest ./docs/ --embed` (downloads 23MB `MongoDB/mdbr-leaf-ir` on first run)
3. Search with hybrid mode: `gnosis-mcp search "how does billing work" --embed`

Or embed existing chunks: `gnosis-mcp embed` (auto-detects local provider).

**To get hybrid search for MCP tool calls** (not just the CLI), set `GNOSIS_MCP_EMBED_PROVIDER=local` in the MCP server's env block. Without it, the server returns keyword-only results regardless of whether your chunks are embedded:

```json
{
  "mcpServers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"],
      "env": {
        "GNOSIS_MCP_EMBED_PROVIDER": "local"
      }
    }
  }
}
```

Override the model with `GNOSIS_MCP_EMBED_MODEL=<huggingface-repo-id>` if you want something other than the default `MongoDB/mdbr-leaf-ir`. If auto-embed fails (network down, wrong model name, missing tokenizer), the server logs a warning and falls back to keyword-only — tool calls never crash because of it.

### PostgreSQL (remote providers)

1. Install with PostgreSQL: `pip install gnosis-mcp[postgres]`
2. Enable pgvector: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Backfill embeddings: `gnosis-mcp embed --provider openai` (or `--provider ollama` for local Ollama)
4. Search with `--embed` flag: `gnosis-mcp search "how does billing work" --embed`

## Optional: Custom Search Function (PostgreSQL)

If you have a PostgreSQL function for hybrid semantic+keyword search:

```json
{
  "env": {
    "GNOSIS_MCP_DATABASE_URL": "postgresql://...",
    "GNOSIS_MCP_SEARCH_FUNCTION": "my_schema.my_search_function"
  }
}
```

Your function must accept `(p_query_text text, p_categories text[], p_limit integer)` and return `(file_path, title, content, category, combined_score)`.
