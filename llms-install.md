# Gnosis MCP — Installation Guide

Three install paths, pick the one that matches how you work:

| You want… | Path | Effort |
|---|---|---|
| **Plugin for Claude Code** — agents, skills, hooks, and the MCP server auto-wired | Path A (plugin marketplace) | One command |
| **Manual control** — cherry-pick which agents/skills land in your config, edit them first | Path B (copy-paste) | ~5 minutes |
| **Just the MCP server** — you don't use Claude Code or don't want the plugin extras | Path C (MCP-only) | Per-editor JSON snippet |

All three paths install the same underlying `gnosis-mcp` Python package. The difference is what wires up around it.

## Prerequisites

- Python 3.11 or later
- A folder of markdown files you want your AI agent to search

No database server required — SQLite works out of the box.

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
cat > .claude/mcp.json <<'JSON'
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
gnosis-mcp check    # verify database connection
gnosis-mcp stats    # see document and chunk counts
gnosis-mcp search "getting started"   # test a search
```

### Step 4: Connect to Your Editor

Add the MCP server config to your editor so your AI agent can search your docs.

**Claude Code** — add to `.claude/mcp.json`:

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

**JetBrains (IntelliJ, PyCharm, WebStorm)** — go to Settings > Tools > AI Assistant > MCP Servers, click +, set command to `gnosis-mcp` and arguments to `serve`.

**Cline** — open the Cline MCP settings panel and add the same server config.

For PostgreSQL, add an env block to any of the above:

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

By default, only read tools (search, get, related) are enabled. To let your AI agent create, update, and delete docs:

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
