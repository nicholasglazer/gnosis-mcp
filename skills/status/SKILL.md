---
name: status
description: Verify gnosis-mcp server connectivity, schema integrity, and corpus health. Use when MCP calls fail, return empty, or return unexpected data.
---

# Status

Diagnostic for "something is wrong with gnosis-mcp". Produces a
compact report the user can screenshot and paste in an issue.

## Usage

```
/gnosis:status              # Full check — connectivity + schema + stats + common failure modes
/gnosis:status quick        # Just connectivity
/gnosis:status stats        # Document / chunk / embedding counts
/gnosis:status diag         # Extended diagnostics (used when something is wrong)
```

## Mode: $ARGUMENTS

---

## Step 1 — connectivity

Preferred path: the MCP itself. If `mcp__gnosis__*` tools respond, the
server is up and MCP is wired correctly.

```
mcp__gnosis__get_graph_stats()
```

If that returns data, skip to Step 2.

### MCP tool not available

Two common causes:

1. **Server not running** — for stdio transport, the MCP client should
   auto-spawn the server. If not: check `.mcp.json` / `.claude/mcp.json`
   config, confirm `gnosis-mcp` is on `PATH`.
2. **Server running, but client not connected** — restart the editor
   once MCP config is correct.

Direct CLI check (works independent of MCP wiring):

```bash
gnosis-mcp check
```

Expected output:

```
Backend: sqlite (SQLite 3.46.0)
Database: /home/<you>/.local/share/gnosis-mcp/docs.db
chunks_table_exists: true (1742 rows)
fts_table_exists:    true
sqlite_vec:          true
vec_table_exists:    true (1742 rows)
links_table_exists:  true (812 rows)
embeddings_coverage: 100.0%
```

If `check` itself returns errors, stop here — the server can't talk to
its own database. Likely causes:

- DB file doesn't exist → `gnosis-mcp init-db`
- DB schema old → `gnosis-mcp init-db` (idempotent, adds any new columns)
- SQLite extension missing (`sqlite_vec: false`) → `pip install 'gnosis-mcp[embeddings]'`

---

## Step 2 — corpus stats

```
mcp__gnosis__get_graph_stats()
```

Report in a compact block:

```
Docs:       412
Chunks:     1,247   (avg 3.0 per doc at current chunk_size)
Orphans:    18      (docs with no graph edges)
Top hubs:
  README.md        37 links
  docs/tools.md    24 links
  docs/config.md   19 links

Edge types:
  related           612
  content_link      410
  git_co_change     225
```

### Reading the signal

- **0 docs**: nothing indexed — tell the user to
  `gnosis-mcp ingest ./docs`
- **docs > 0 but chunks == 0**: schema drift; `gnosis-mcp init-db`
  followed by a re-ingest
- **avg chunks per doc > 15**: either your chunk size is too small
  (default is 2000 chars; check `GNOSIS_MCP_CHUNK_SIZE`) or your docs
  are huge
- **orphans > 40 % of total**: graph is flat; users aren't using
  `relates_to:` frontmatter or `[markdown](links.md)`
- **edge distribution heavily git_co_change**: the curated knowledge
  is thin; git ingest is dominating. Consider pruning git history
  with `--since 3m` or removing `ingest-git`

---

## Step 3 — embeddings

```bash
gnosis-mcp stats
```

Look for:

```
Chunks with NULL embeddings: 0  ✓
```

If non-zero, embeddings are partial. Fix:

```bash
gnosis-mcp embed       # backfill the missing ones
```

If that command errors about a missing provider, the user doesn't have
the `[embeddings]` extra installed:

```bash
pip install 'gnosis-mcp[embeddings]'
```

---

## Step 4 — reranker (only if `diag` mode or user reports slow search)

```bash
python -c "from gnosis_mcp.rerank import get_reranker; get_reranker().score('test', ['test passage'])"
```

Failure modes:

- `ImportError` → `[reranking]` extra not installed
- `HTTPError 401/404` on model download → model URL stale. If the
  default model returns 401, override:
  `GNOSIS_MCP_RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2`
- First call takes 60+ s → model download in progress (check
  `~/.local/share/gnosis-mcp/rerankers/`)

**Reminder for users enabling reranking**: our measurements show
MS-MARCO-class rerankers hurt dev-doc retrieval by ~27 nDCG@10.
Disable unless `/gnosis:tune full` confirms it helps on the user's
specific corpus.

---

## Step 5 — server transport (HTTP deployments only)

If the server runs as streamable-HTTP (not stdio):

```bash
curl -fsS http://127.0.0.1:8000/health | jq .
```

Expected:

```json
{
  "status": "ok",
  "version": "0.11.0",
  "docs": 412,
  "chunks": 1247,
  "backend": "sqlite"
}
```

Common failures:

- Connection refused → server isn't running
- 401 → `GNOSIS_MCP_API_KEY` is set but the probe didn't send a Bearer
  token. Note: `/health` is always public; 401 there suggests an
  unusual reverse-proxy config
- 500 → check server logs (`journalctl -u gnosis-mcp -f` or
  `docker logs gnosis-mcp`)

---

## Step 6 — access log (diag mode)

If users complain about stale "most popular" results from
`get_context`:

```sql
-- in the SQLite DB:
SELECT count(*) FROM search_access_log WHERE timestamp > datetime('now', '-30 days');
```

- Zero rows and `GNOSIS_MCP_ACCESS_LOG=false` → logging disabled by
  config (intentional for privacy-sensitive deployments)
- Zero rows and logging enabled → `search_docs` + `get_doc` haven't
  been called yet; expected on a fresh install

Purge old rows with `gnosis-mcp cleanup --days 30` (weekly cron).

---

## Quick mode

Just steps 1 and 2. Skip embeddings/reranker/transport checks.

```
Connectivity: ✓
Docs:         412 / Chunks: 1,247
```

---

## Full report format

Always include these fields when giving the user a status summary:

```
## gnosis-mcp status

Server:       running (stdio | streamable-http) · v0.11.0
Backend:      sqlite / postgres
DB path:      ~/.local/share/gnosis-mcp/docs.db
Schema:       current ✓
Docs:         412
Chunks:       1,247 (avg 3.0/doc)
Embeddings:   1,247 / 1,247 (100 %)
Chunk size:   2000 chars (v0.11 default)
Writable:     false  (set GNOSIS_MCP_WRITABLE=true to enable upserts)
Reranker:     disabled  (recommended on dev docs)
Access log:   enabled, 1,289 entries in last 30 days

Known issues: none   OR   <list each found>
Recommended:  <one-line next action>
```

---

## See also

- `/gnosis:setup` — first-time setup wizard
- `/gnosis:ingest` — populate / re-populate / prune the corpus
- `/gnosis:tune` — find the chunk size / retrieval config optimum
- [Troubleshooting guide](https://gnosismcp.com/doc/docs/troubleshooting)
  for every known error message
