---
title: MCP Tools Reference
category: docs
audience: all
relates_to:
  - README.md
  - docs/config.md
  - docs/cli.md
  - docs/rest-api.md
---

# MCP Tools Reference

gnosis-mcp exposes **9 tools** and **3 resources** over the Model Context
Protocol. The same API surface is available via stdio, streamable-HTTP, and
(opt-in) a REST mirror on the HTTP port.

Tools marked *read* are always available. Tools marked *write* require
`GNOSIS_MCP_WRITABLE=true`.

---

## Read tools

### `search_docs`

Keyword (FTS5/tsvector), hybrid (keyword + vector), or custom-function search.
The primary entry point for most agents.

**Parameters**

| Name              | Type             | Default | Description                                                       |
| ----------------- | ---------------- | ------- | ----------------------------------------------------------------- |
| `query`           | `string`         | —       | Search text. ≤ `GNOSIS_MCP_MAX_QUERY_CHARS` (default 10 000).     |
| `category`        | `string`         | `null`  | Filter by `category` column (e.g. `"guides"`, `"architecture"`).  |
| `limit`           | `integer`        | `5`     | Max results. Clamped to `GNOSIS_MCP_SEARCH_LIMIT_MAX` (default 20). |
| `query_embedding` | `list[float]`    | `null`  | Pre-computed vector. Enables hybrid ranking via RRF.              |

**Auto-embedding.** When `query_embedding` is omitted and a local ONNX
provider is configured, gnosis-mcp embeds the query in-process and runs
hybrid search automatically.

**Hybrid ranking.** Hybrid search fuses BM25 (keyword) and cosine similarity
(vector) via Reciprocal Rank Fusion. The fusion constant is tunable:
`GNOSIS_MCP_RRF_K` (default `60`). Higher `K` flattens the curve and lets
vector scores contribute more.

**Returns**

```json
[
  {
    "file_path": "guides/quickstart.md",
    "chunk_index": 0,
    "title": "Quickstart",
    "category": "guides",
    "content": "…preview…",
    "score": 0.0416
  }
]
```

**Errors**
- `InvalidParams` — `query` empty or over `GNOSIS_MCP_MAX_QUERY_CHARS`.

---

### `get_doc`

Reassemble a document's chunks in order.

**Parameters**

| Name         | Type       | Default | Description                                     |
| ------------ | ---------- | ------- | ----------------------------------------------- |
| `path`       | `string`   | —       | Document `file_path` (exact match).             |
| `max_length` | `integer`  | `null`  | Truncate body at N characters with a `…` suffix. |

**Returns.** A single object:

```json
{
  "file_path": "guides/quickstart.md",
  "title": "Quickstart",
  "category": "guides",
  "content": "# Quickstart\n\n…full body…",
  "chunks": 4
}
```

---

### `get_related`

Walk the document link graph — returns neighbours up to `depth` hops away.

**Parameters**

| Name              | Type     | Default | Description                                                    |
| ----------------- | -------- | ------- | -------------------------------------------------------------- |
| `path`            | `string` | —       | Starting document.                                             |
| `depth`           | `int`    | `1`     | Hops. `1` = direct neighbours, `2` = their neighbours, up to `3`. |
| `relation_type`   | `string` | `null`  | Filter by edge type (e.g. `related`, `content_link`, `git_co_change`). |
| `include_titles`  | `bool`   | `false` | Include `title` + `category` on each result.                   |

**Edge types.** gnosis-mcp derives edges from several sources:
- `related` — default `relates_to:` frontmatter
- Typed relations from the `relations:` frontmatter block
  (`prerequisite`, `depends_on`, `summarizes`, `extends`, `replaces`,
  `audited_by`, `implements`, `tests`, `example_of`, `references`, and
  their inverses)
- `content_link` — markdown `[text](path.md)` links and `[[wikilinks]]`
- `git_co_change` — files co-edited in the same commit
- `git_ref` — source file reference in a commit history doc

**Returns**

```json
[
  { "source": "guides/quickstart.md", "target": "guides/ingest.md",
    "relation_type": "content_link", "hops": 1 }
]
```

---

### `search_git_history`

Search indexed git commit-history documents. Requires a prior
`gnosis-mcp ingest-git …` run.

**Parameters**

| Name        | Type      | Description                                          |
| ----------- | --------- | ---------------------------------------------------- |
| `query`     | `string`  | Search text (commit messages, file names, authors).  |
| `author`    | `string?` | Substring match on author name or email.             |
| `since`     | `string?` | `YYYY-MM-DD` — commits after.                        |
| `until`     | `string?` | `YYYY-MM-DD` — commits before.                       |
| `file_path` | `string?` | Restrict to a single file's history.                 |
| `limit`     | `int`     | Max results (default `5`).                           |

Useful for answering "why does this code exist?" — finds the commit that
introduced a line rather than the line itself.

---

### `get_context`

Usage-weighted context summary. Two modes:

- **Topical** — `topic` provided. Runs search, enriches with access counts,
  returns the most-visited docs that match.
- **Global** — no `topic`. Returns the overall most-accessed docs plus
  high-level stats.

**Parameters**

| Name       | Type      | Default | Description                                    |
| ---------- | --------- | ------- | ---------------------------------------------- |
| `topic`    | `string?` | `null`  | Optional focus.                                |
| `limit`    | `int`     | `10`    | Max docs.                                      |
| `category` | `string?` | `null`  | Restrict to a category.                        |

**Returns** a compact orientation summary (doc paths, titles, access counts,
categories). Designed for LLMs at session-start to prime working context.

---

### `get_graph_stats`

Knowledge-graph topology: orphan docs, hub docs (high degree), edge type
distribution, totals.

**Parameters**

| Name       | Type      | Description                     |
| ---------- | --------- | ------------------------------- |
| `category` | `string?` | Filter orphan detection scope.  |

**Returns**

```json
{
  "nodes": 412,
  "edges": 1_247,
  "orphans": 18,
  "hubs": [
    {"path": "README.md", "degree": 37},
    {"path": "docs/tools.md", "degree": 24}
  ],
  "by_relation_type": {
    "related": 612, "content_link": 410, "git_co_change": 225
  }
}
```

---

## Write tools

All write tools refuse when `GNOSIS_MCP_WRITABLE` is unset or `false`.
They also fire a fire-and-forget POST to `GNOSIS_MCP_WEBHOOK_URL` (if set)
so downstream systems can invalidate caches. See [config.md](config.md#webhooks)
for the SSRF-guard details.

### `upsert_doc`

Insert or replace a document. Splits content into chunks at paragraph
boundaries if it exceeds `GNOSIS_MCP_CHUNK_SIZE`.

**Parameters**

| Name         | Type              | Description                                                             |
| ------------ | ----------------- | ----------------------------------------------------------------------- |
| `path`       | `string`          | `file_path` (required). Used as primary key.                            |
| `content`    | `string`          | Full body. Rejected if longer than `GNOSIS_MCP_MAX_DOC_BYTES` (50 MB).   |
| `title`      | `string?`         | Falls back to first H1 of `content`.                                    |
| `category`   | `string?`         | Default `"all"`.                                                        |
| `audience`   | `string?`         | Default `"all"`.                                                        |
| `tags`       | `list[string]?`   | Stored per-chunk.                                                       |
| `embeddings` | `list[list[f32]]?`| Pre-computed vectors, one per chunk. Length must match split count.      |

Existing chunks for this `path` are deleted and replaced atomically. Use
[`update_metadata`](#update_metadata) if you only want to change headers.

### `delete_doc`

Remove a document and all its chunks/links.

**Parameters**

| Name   | Type     | Description             |
| ------ | -------- | ----------------------- |
| `path` | `string` | File path to delete.    |

### `update_metadata`

Change metadata fields on every chunk of a document. Omitted fields stay
unchanged.

**Parameters**

| Name       | Type              |
| ---------- | ----------------- |
| `path`     | `string`          |
| `title`    | `string?`         |
| `category` | `string?`         |
| `audience` | `string?`         |
| `tags`     | `list[string]?`   |

---

## Resources

Resources are a read-only discovery surface. Clients call them via MCP's
`resources/list` and `resources/read`.

| URI                         | Returns                                               |
| --------------------------- | ----------------------------------------------------- |
| `gnosis://docs`             | List of all documents (path, title, category, chunks). |
| `gnosis://docs/{path}`      | Full content of one document by path.                 |
| `gnosis://categories`       | Categories with doc counts.                           |

---

## See also

- [CLI reference](cli.md) — how to populate the index.
- [Config reference](config.md) — environment variables that change tool
  behaviour (size caps, limits, backends, webhooks).
- [REST API](rest-api.md) — same surface over HTTP when `--rest` is on.
