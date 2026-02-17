---
name: search
description: Search knowledge base documentation via Gnosis MCP. Keyword search (default) or hybrid semantic+keyword (--semantic).
---

# Documentation Search

Search across all indexed documentation using Gnosis MCP.

## Usage
```
/gnosis:search billing credits
/gnosis:search how does authentication work
/gnosis:search --semantic webhook processing    # Hybrid semantic+keyword
/gnosis:search --category guides setup          # Filter by category
```

## Query: $ARGUMENTS

## Process

### Default: Keyword Search

1. **Search via Gnosis MCP** `search_docs` tool:

```
Tool: mcp__gnosis__search_docs
Arguments:
  query: "$ARGUMENTS"
  limit: 8
```

2. **Format results** as a table:

| # | Score | Title | Path | Snippet |
|---|-------|-------|------|---------|
| 1 | 0.85 | Auth Guide | curated/guides/auth.md | ... |

- Show **top 5 results**
- Include a 1-2 sentence snippet per result
- To read a full doc, use `mcp__gnosis__get_doc` with the path

3. **If no results or low scores** (all < 0.1):
   - Broaden the query (synonyms, fewer terms)
   - Try `mcp__gnosis__get_doc` to read a specific doc directly

### `--semantic`: Hybrid Search

For meaning-based matching (not just keyword overlap):

1. **Generate embedding** via the Gnosis embed CLI:
```bash
gnosis-mcp embed --query "$ARGUMENTS"
```

2. **If embed CLI is unavailable**, fall back to multi-query keyword search:
   - Break the query into synonyms and related terms
   - Run 2-3 keyword searches with different phrasings
   - Merge and deduplicate results by path
   - Rank by highest score

3. **Format results** the same as keyword mode but note the search mode used.

### `--category`: Filter by Category

Pass `category` param to `search_docs` to filter results:
```
Tool: mcp__gnosis__search_docs
Arguments:
  query: "$ARGUMENTS"
  category: "guides"
  limit: 8
```

## Notes

- Default keyword search uses PostgreSQL tsvector (fast, no GPU needed)
- Hybrid search uses pgvector embeddings + keyword scoring
- Embedding model dimension: configurable (default 384 for HNSW cosine index)
