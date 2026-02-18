---
name: setup
description: First-time setup wizard for Gnosis MCP. Initializes database, ingests docs, and configures MCP client.
---

# Gnosis MCP Setup

First-time setup wizard. Gets you from install to working search in 60 seconds.

## Usage
```
/gnosis:setup                    # Interactive setup (auto-detect backend)
/gnosis:setup /path/to/docs      # Setup + ingest a specific docs folder
```

## Target: $ARGUMENTS

## Process

### Step 1: Check Installation

```bash
gnosis-mcp --version
```

If not installed:
```bash
pip install gnosis-mcp              # SQLite (zero-config)
pip install gnosis-mcp[postgres]    # + PostgreSQL support
```

### Step 2: Detect Backend

Check for `GNOSIS_MCP_DATABASE_URL` environment variable:

- **Not set** → SQLite backend (default, zero-config)
- **Set to `postgresql://...`** → PostgreSQL backend

Report which backend will be used.

### Step 3: Initialize Database

```bash
gnosis-mcp init-db
```

This is idempotent — safe to run multiple times.

### Step 4: Ingest Documentation

If a path was provided in `$ARGUMENTS`:
```bash
gnosis-mcp ingest "$ARGUMENTS"
```

If no path provided, ask the user where their documentation lives.

Preview first with `--dry-run`:
```bash
gnosis-mcp ingest /path/to/docs --dry-run
```

### Step 5: Verify

```bash
gnosis-mcp check
gnosis-mcp stats
```

### Step 6: Report

```
## Gnosis MCP Setup Complete

| Setting | Value |
|---------|-------|
| Backend | SQLite / PostgreSQL |
| Database | ~/.local/share/gnosis-mcp/docs.db |
| Documents | 42 |
| Chunks | 460 |
| FTS | ready |

Next steps:
- Search: `gnosis-mcp search "your query"`
- Add to MCP client: see `gnosis-mcp --help`
- Enable writes: set `GNOSIS_MCP_WRITABLE=true`
```

## Notes

- SQLite is the default — no database server needed
- PostgreSQL requires `pip install gnosis-mcp[postgres]` and a running PG instance
- Re-running ingest skips unchanged files (content hashing)
- FTS5 (SQLite) or tsvector (PostgreSQL) powers keyword search out of the box
