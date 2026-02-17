---
name: manage
description: CRUD operations for knowledge base docs — add, delete, update metadata, embed. Requires GNOSIS_MCP_WRITABLE=true.
disable-model-invocation: true
---

# Documentation Manager

CRUD operations for your knowledge base via Gnosis MCP.

## Usage
```
/gnosis:manage add path/to/doc.md                 # Index a document
/gnosis:manage delete path/to/doc.md               # Remove a document
/gnosis:manage update path/to/doc.md --tags api,auth  # Update metadata
/gnosis:manage embed path/to/docs/                 # Bulk embed a directory
/gnosis:manage search-related path/to/doc.md       # Find related docs
```

## Action: $ARGUMENTS

---

## `add` — Index a Document

1. **Read the file** from the provided path
2. **Extract metadata**: title (first H1), category (from frontmatter or directory)
3. **Upsert to Gnosis**:

```
Tool: mcp__gnosis__upsert_doc
Arguments:
  path: "{relative_path}"
  content: "{file_content}"
  title: "{extracted_title}"
  category: "{category}"
  tags: ["{tag1}", "{tag2}"]
```

4. **Verify** the doc is retrievable:
```
Tool: mcp__gnosis__get_doc
Arguments:
  path: "{relative_path}"
```

5. **Report** path, title, chunk count.

---

## `delete` — Remove a Document

1. **Delete from Gnosis**:
```
Tool: mcp__gnosis__delete_doc
Arguments:
  path: "{relative_path}"
```

2. **Verify** deletion (get_doc should return empty).
3. **Report** what was removed.

---

## `update` — Update Metadata

1. **Parse flags**: `--title`, `--category`, `--tags`, `--audience`
2. **Update via Gnosis**:

```
Tool: mcp__gnosis__update_metadata
Arguments:
  path: "{relative_path}"
  title: "{new_title}"
  category: "{new_category}"
  tags: ["{tag1}", "{tag2}"]
```

3. **Report** updated fields.

---

## `embed` — Bulk Embed Directory

Index all markdown files in a directory:

1. **List markdown files** in the target path
2. **For each file**, read and upsert:
```
Tool: mcp__gnosis__upsert_doc
Arguments:
  path: "{relative_path}"
  content: "{file_content}"
  title: "{title}"
  category: "{category}"
```
3. **Report** total files processed and chunk counts.

---

## `search-related` — Find Related Documents

1. **Query the link graph**:
```
Tool: mcp__gnosis__get_related
Arguments:
  path: "{relative_path}"
```

2. **Format results** as a list of related docs with relationship types.

## Notes

- All write operations require `GNOSIS_MCP_WRITABLE=true`
- Gnosis auto-chunks documents at H2 boundaries (~4000 chars per chunk)
- Content hashing prevents re-indexing unchanged files during bulk embed
- Frontmatter (title, category, audience, tags) is extracted automatically
