---
name: context
description: Load usage-weighted context from Gnosis MCP. Surfaces most-accessed docs for session startup or topic primers.
---

# Context Loading

Load a compact context summary from your knowledge base — prioritized by actual usage patterns.

## Usage
```
/gnosis:context                          # Top docs by access frequency
/gnosis:context deployment               # Topic-focused context
/gnosis:context --category guides        # Filter by category
/gnosis:context --limit 5 auth           # Limit results
```

## Query: $ARGUMENTS

## Process

### Without topic (session startup)

Get the most-accessed documents — what matters most based on real usage:

```
Tool: mcp__gnosis__get_context
Arguments:
  limit: 10
```

### With topic

Get topic-relevant docs enriched with access frequency:

```
Tool: mcp__gnosis__get_context
Arguments:
  topic: "$ARGUMENTS"
  limit: 10
```

### With `--category` flag

```
Tool: mcp__gnosis__get_context
Arguments:
  topic: "$ARGUMENTS"
  category: "{category}"
  limit: 10
```

## Output Format

```
## Context Summary

**Top documents:**
| # | Title | Category | Accesses | Path |
|---|-------|----------|----------|------|
| 1 | Auth Guide | guides | 47 | curated/guides/auth.md |

**Stats:**
- Total docs: 571
- Total chunks: 14,582
- Categories: guides (38), architecture (12), ...
```

## Notes

- Access tracking is automatic — `search_docs` and `get_doc` log usage
- First call with no access history returns empty docs + stats only
- Disable tracking: `GNOSIS_MCP_ACCESS_LOG=false`
- Purge old entries: `gnosis-mcp cleanup --days 90`
