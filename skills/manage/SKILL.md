---
name: manage
description: CRUD operations on the knowledge base — add, delete, update metadata. For bulk ingest / re-ingest / prune, use /gnosis:ingest instead. Requires GNOSIS_MCP_WRITABLE=true.
disable-model-invocation: true
---

# Manage

Single-document CRUD against the gnosis-mcp knowledge base. Bulk
operations (full re-ingest, git history, web crawl, prune) live in
`/gnosis:ingest` — this skill is for point changes.

All write operations require `GNOSIS_MCP_WRITABLE=true` on the server
process. If the server refuses, it returns a structured error — relay
that to the user rather than swallowing it.

## Usage

```
/gnosis:manage add path/to/doc.md                   # Index a single document
/gnosis:manage delete path/to/doc.md                # Remove one document
/gnosis:manage update path/to/doc.md --tags api,auth  # Patch metadata
/gnosis:manage related path/to/doc.md               # List link neighbours
/gnosis:manage stats                                 # Corpus inventory + health
```

Bulk actions — see `/gnosis:ingest`:

- `ingest ./docs --prune` — re-ingest + drop chunks for missing files
- `ingest ./docs --wipe` — nuclear reset + reindex
- `ingest git <repo>` — commit history
- `ingest crawl <url>` — web crawl

## Action: $ARGUMENTS

---

## `add` — index a single document

1. **Read** the file at `$path` from disk.
2. **Extract metadata**:
   - Title: frontmatter `title:` if present, else first H1
   - Category: frontmatter `category:`, else first path segment
   - Audience: frontmatter `audience:`, default `"all"`
   - Tags: frontmatter `tags:` as a list
3. **Upsert** via `mcp__gnosis__upsert_doc`:
   ```
   path: "<relative path from repo root>"
   content: "<full file content>"
   title: "<extracted>"
   category: "<extracted>"
   audience: "<extracted>"
   tags: [...]
   ```
4. **Verify** via `mcp__gnosis__get_doc(path=<path>)` — expect the
   document back. If it returns empty, writes aren't enabled on the
   server or there was a silent failure.
5. **Report** `{path, title, chunks_written}` — chunk count should
   roughly be `len(content) / 2000` at the v0.11 default chunk size.

### Content size cap

`upsert_doc` refuses content larger than `GNOSIS_MCP_MAX_DOC_BYTES`
(default 50 MB). For bigger files: split them or bump the cap.

### Pre-computed embeddings

If you have vectors from your own pipeline, pass them:

```
embeddings: [[0.12, 0.04, ...], [0.08, ...]]
```

One vector per chunk *after* the server-side chunker runs. The server
won't re-embed; it'll trust what you pass.

---

## `delete` — remove one document

```
mcp__gnosis__delete_doc(path="<relative path>")
```

Returns `{chunks_deleted, links_deleted}`. Verify by re-fetching:

```
mcp__gnosis__get_doc(path="<relative path>")  # → empty
```

If you're *reorganising* the knowledge folder and want to drop every
chunk whose source file is gone: don't loop `delete_doc` — use
`/gnosis:ingest prune <root>` which walks the corpus once.

---

## `update` — patch metadata (no content change)

For title / category / audience / tags changes without re-chunking.

Parse flags from `$ARGUMENTS`:

| Flag | Maps to |
|---|---|
| `--title "New Title"` | `title` |
| `--category guides` | `category` |
| `--audience internal` | `audience` |
| `--tags api,auth,billing` | `tags` (comma-split → list) |

Call `mcp__gnosis__update_metadata` with only the fields the user
specified. Omitted fields are untouched.

Report the patched fields. If the document doesn't exist, the server
returns an error — relay it.

---

## `related` — explore the link graph

```
mcp__gnosis__get_related(path="<relative path>", depth=2, include_titles=True)
```

Returns neighbours up to 2 hops away with their titles and relation
types. Summary format:

```
Direct (1-hop):
  guides/auth-guide.md          [related]
  architecture/auth.md          [content_link]

2-hop:
  runbooks/stripe-auth.md       [content_link → content_link]
  git-history/src/auth.py.md    [git_ref]
```

Filter by relation type if the user wants signal vs noise:

- `relation_type="content_link"` — only explicit markdown links
- `relation_type="related"` — only `relates_to:` frontmatter
- `relation_type="git_co_change"` — only files touched in the same
  commits

---

## `stats` — corpus inventory

Read-only, doesn't need `WRITABLE`. Good "am I running the server I
think I am?" check.

```
mcp__gnosis__get_graph_stats()
```

Report:

```
docs         412
chunks     1,247
orphans       18         # nodes with zero edges
hubs:
  README.md              37 links
  docs/tools.md          24 links
  docs/config.md         19 links
edges by type:
  related           612
  content_link      410
  git_co_change     225
```

Useful for spotting a too-flat graph (many orphans) or a single
megahub (star-shaped corpus).

---

## See also

- `/gnosis:ingest` — bulk operations (first ingest, re-ingest, prune,
  git history, web crawl)
- `/gnosis:search` — queries that return docs
- `/gnosis:status` — server connectivity + schema health
- [MCP tool reference](https://gnosismcp.com/doc/docs/tools) —
  every tool and parameter

---

## Reminders

- All write tools require `GNOSIS_MCP_WRITABLE=true`
- Gnosis chunks at H2 boundaries, with a default target of **2000
  characters** per chunk in v0.11 (was 4000 in v0.10)
- Content hashing is per-chunk — unchanged files skip re-processing on
  subsequent ingests
- Frontmatter is extracted automatically (`title`, `category`,
  `audience`, `tags`, `relates_to`, `relations`)
- Writes trigger a webhook if `GNOSIS_MCP_WEBHOOK_URL` is set
  (SSRF-guarded — private IPs refused unless `_WEBHOOK_ALLOW_PRIVATE=true`)
