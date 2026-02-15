# Gnosis MCP — Installation Guide

## Prerequisites

- Python 3.11 or later
- PostgreSQL with pgvector extension
- A documentation table (or use `gnosis-mcp init-db` to create one), or just a folder of markdown files

## Step 1: Install

```bash
pip install gnosis-mcp
```

Or with uvx (no install needed):

```bash
uvx gnosis-mcp serve
```

## Step 2: Set Database URL

```bash
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
```

## Step 3: Initialize Database (optional)

If you don't have documentation tables yet:

```bash
gnosis-mcp init-db
```

This creates the chunks table, links table, indexes, and a basic search function. Safe to run multiple times (idempotent).

## Step 4: Load Your Docs

Point at a folder of markdown files:

```bash
gnosis-mcp ingest ./docs/
```

This scans all `.md` files, chunks by H2 headings, extracts metadata from frontmatter, and inserts into PostgreSQL. Re-running skips unchanged files.

Preview without writing:

```bash
gnosis-mcp ingest ./docs/ --dry-run
```

## Step 5: Verify

```bash
gnosis-mcp check
```

## Step 6: Add to MCP Client

Add this to your MCP client configuration:

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

### Config file locations

| Client | Config Path |
|--------|------------|
| Claude Code | `.claude/mcp.json` |
| Cursor | `.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Cline | Cline MCP settings panel |

## Optional: Enable Write Mode

```json
{
  "env": {
    "GNOSIS_MCP_DATABASE_URL": "postgresql://...",
    "GNOSIS_MCP_WRITABLE": "true"
  }
}
```

## Optional: Custom Hybrid Search

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
