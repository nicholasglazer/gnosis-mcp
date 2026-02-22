# Gnosis MCP — Installation Guide

## Prerequisites

- Python 3.11 or later
- A folder of markdown files you want your AI agent to search

No database server required — SQLite works out of the box.

## Step 1: Install

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

## Step 2: Load Your Docs

Point at a folder of markdown files:

```bash
gnosis-mcp ingest ./docs/
```

This auto-creates the SQLite database at `~/.local/share/gnosis-mcp/docs.db`, scans all `.md` files, chunks them by H2 headings, extracts metadata from frontmatter, and inserts into the database. Re-running skips unchanged files — safe to run as often as you like.

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

## Step 3: Verify

```bash
gnosis-mcp check    # verify database connection
gnosis-mcp stats    # see document and chunk counts
gnosis-mcp search "getting started"   # test a search
```

## Step 4: Connect to Your Editor

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
2. Ingest with embeddings: `gnosis-mcp ingest ./docs/ --embed` (downloads 23MB model on first run)
3. Search with hybrid mode: `gnosis-mcp search "how does billing work" --embed`

Or embed existing chunks: `gnosis-mcp embed` (auto-detects local provider)

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
