# Gnosis MCP — Installation Guide

## Prerequisites

- Python 3.11 or later
- A folder of markdown files to index

No database server required — SQLite works out of the box.

## Step 1: Install

```bash
pip install gnosis-mcp
```

Or with uvx (no install needed):

```bash
uvx gnosis-mcp serve
```

For PostgreSQL support:

```bash
pip install gnosis-mcp[postgres]
```

## Step 2: Load Your Docs

Point at a folder of markdown files:

```bash
gnosis-mcp ingest ./docs/
```

This auto-creates the SQLite database at `~/.local/share/gnosis-mcp/docs.db`, scans all `.md` files, chunks by H2 headings, extracts metadata from frontmatter, and inserts into the database. Re-running skips unchanged files.

For PostgreSQL, set the URL first and initialize the schema:

```bash
export GNOSIS_MCP_DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
gnosis-mcp init-db
gnosis-mcp ingest ./docs/
```

Preview without writing:

```bash
gnosis-mcp ingest ./docs/ --dry-run
```

## Step 3: Verify

```bash
gnosis-mcp check
```

## Step 4: Add to MCP Client

Add this to your MCP client configuration:

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

For PostgreSQL, add the env block:

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
    "GNOSIS_MCP_WRITABLE": "true"
  }
}
```

## Optional: Custom Hybrid Search (PostgreSQL)

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
