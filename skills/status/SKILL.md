---
name: status
description: Verify Gnosis MCP server connectivity, check document stats, and diagnose issues. Use when Gnosis MCP calls fail or return unexpected results.
---

# Gnosis Status

Verify Gnosis MCP server connectivity, check document stats, and diagnose issues.

## Usage
```
/gnosis:status              # Full health check
/gnosis:status quick        # Just connectivity
/gnosis:status stats        # Document statistics only
```

## Mode: $ARGUMENTS

## Process

### Step 1: Connectivity Check

Test that the Gnosis MCP server is responding:

```
Tool: mcp__gnosis__search_docs
Arguments:
  query: "test"
  limit: 1
```

If this succeeds, Gnosis is connected and the database is reachable.
If this fails, report the error and see Troubleshooting below.

For `quick` mode, stop here.

### Step 2: Document Statistics (default + stats mode)

```
Resource: gnosis://docs
Resource: gnosis://categories
```

### Step 3: Report

```
## Gnosis MCP Status

| Check | Status |
|-------|--------|
| MCP Server | Connected |
| Database | Reachable |

### Document Statistics
| Category | Docs | Chunks |
|----------|------|--------|
| guides | 38 | 583 |
| ... | ... | ... |
```

## Troubleshooting

### Gnosis not responding
1. Check if gnosis-mcp is installed: `gnosis-mcp --version`
2. Check if the MCP server entry exists in Claude Code's MCP config
3. Verify `GNOSIS_MCP_DATABASE_URL` is set and correct
4. Start manually: `gnosis-mcp serve`

### Database connection failed
1. Check PostgreSQL is running
2. Verify the connection string in `GNOSIS_MCP_DATABASE_URL`
3. Test direct connection: `psql "$GNOSIS_MCP_DATABASE_URL" -c "SELECT 1"`

### Search returns no results
1. Check if documents are indexed: `gnosis-mcp stats`
2. If zero docs, ingest your documentation: `gnosis-mcp ingest /path/to/docs`
3. Verify the search function exists in your database

### Write operations fail
1. Verify `GNOSIS_MCP_WRITABLE=true` is set
2. Check database user has INSERT/UPDATE/DELETE permissions

## Notes

- 6 tools: search_docs, get_doc, get_related (read) + upsert_doc, delete_doc, update_metadata (write)
- 3 resources: gnosis://docs, gnosis://docs/{path}, gnosis://categories
- Write tools require `GNOSIS_MCP_WRITABLE=true`
