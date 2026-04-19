# Agents for gnosis-mcp

Subagent definitions for [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
(and any other MCP client that supports the `agents/` folder
convention). The goal: you shouldn't have to write your own "how to
talk to gnosis-mcp" prompt — these are the ones we use ourselves.

## Install

See [`../llms-install.md`](../llms-install.md). Three paths — plugin
marketplace (one command), manual copy-paste (pick specific agents),
or MCP-server-only (no agents at all). This folder covers the
agent-specific details; install mechanics live in the single canonical
guide.

---

## The roster

| Agent | Model | Purpose | Pairs with skill |
|---|---|---|---|
| **context-loader** | haiku | Fast doc-graph primer — pulls the most-accessed docs before you start | `/gnosis:context` |
| **doc-explorer** | sonnet | Read-only navigator — search, follow the link graph, cross-reference git | `/gnosis:search` |
| **doc-keeper** | sonnet | Single-file CRUD + drift audits — upsert, delete, update metadata | `/gnosis:manage` |
| **corpus-sync** | sonnet | Bulk lifecycle — file ingest, git history, web crawl, prune, re-embed | `/gnosis:ingest` |
| **doc-reviewer** | sonnet | Pre-release audit — cross-refs docs against real code, reports drift | (produces reports, no skill pair) |

### Which one do I spawn when?

- *"Before I start this task, remind me what we already have"* → `context-loader`
- *"Find me the docs about X"* → `doc-explorer`
- *"I added a new doc / reorganized the folder / want to index a vendor site"* → `corpus-sync`
- *"I need to add / delete / retag one specific file"* → `doc-keeper`
- *"Pre-release: are these docs accurate against current code?"* → `doc-reviewer`

---

## What each one does

### context-loader (haiku, cheap)

Lightweight session-start agent. Runs `get_context()` to pull the
usage-weighted top docs for a topic, then optionally drills into the
most relevant one with `get_doc`. Returns a compact structured summary
under 300 words.

```
"Load context about our billing architecture"
→ get_context(topic="billing architecture")
→ summary of top 5 docs + their access counts
```

Use at the start of any task where "what do we already know about X?"
matters.

### doc-explorer (sonnet, read-only)

Search-heavy navigator. Starts with `search_docs`, drills with
`get_doc`, traverses with `get_related`, cross-references source code
with `Read`/`Glob`/`Grep`, and pulls commit history via
`search_git_history` when the user asks "why".

```
"How does our authentication work?"
→ search_docs("authentication")
→ get_doc(top hit)
→ get_related(that path, depth=2) for connected docs
→ Grep for the auth functions mentioned in the doc
→ structured answer with citations
```

Never writes. If the user wants a doc changed, it hands off to
`doc-keeper` or `corpus-sync`.

### doc-keeper (sonnet, single-file writes)

The surgeon — precise, single-file changes. Adds one doc, deletes one
doc, patches metadata without re-chunking. Also runs the drift-audit
playbook: find docs related to a feature, compare against the code,
report discrepancies without modifying anything.

```
"Add the new deployment-safety guide to the index"
→ Read the file
→ extract frontmatter / title / category
→ upsert_doc(...)
→ get_doc(...) to verify
→ report chunks written

"Review all affiliate-system docs for drift against code"
→ search_docs("affiliate")
→ get_doc each hit
→ Grep the source tree for function names mentioned in the doc
→ drift report with file:line evidence
```

Requires `GNOSIS_MCP_WRITABLE=true` on the server for any write.

### corpus-sync (sonnet, bulk ingestion)

The lifecycle operator. Owns `gnosis-mcp ingest`, `ingest-git`,
`crawl`, `prune`, `embed`. Handles the flag matrix (`--prune`,
`--wipe`, `--include-crawled`, `--since`, `--sitemap`, etc.) so you
don't have to memorize it.

```
"I reorganized the docs folder — the old paths are dead"
→ gnosis-mcp ingest ./docs --embed --prune
→ confirms old paths gone, new paths present
→ before/after stats

"Index stripe.com into my local knowledge base"
→ asks for user OK (always)
→ gnosis-mcp crawl https://docs.stripe.com --sitemap --embed --include "/docs/api/**"
→ reports pages indexed
```

Always runs `gnosis-mcp stats` before and after so you see the deltas.
Never runs `--wipe` without explicit user consent.

### doc-reviewer (sonnet, read-only)

Pre-release gate. For each doc in scope: reads the doc, greps the
source code for every function / config / endpoint mentioned, checks
whether they still exist and match the claims. Produces a line-item
drift report.

```
"Audit the docs/integrations/shopify/ folder for drift"
→ list docs in that folder via gnosis search + filesystem
→ for each: extract code references
→ grep source code for each reference
→ drift findings: "docs claim X; code does Y; evidence at path:line"
```

Never modifies docs. Report is input for the human or for
`doc-keeper` to act on.

---

## How they compose (common flows)

### Daily: searching before coding

```
spawn: context-loader
  ↓
  "Working on the billing refactor; load relevant docs"
  ↓ (returns 5 top docs on billing)

spawn: doc-explorer
  ↓
  "Tell me how the Stripe webhook signature verification works"
  ↓ (searches, reads, explains with citations)
```

### After a feature ships

```
spawn: corpus-sync
  ↓
  "Index the new docs I wrote in docs/features/price-rules/"
  ↓ (gnosis-mcp ingest → stats delta)

spawn: doc-reviewer     (optional, before release)
  ↓
  "Audit all price-rules docs against the actual implementation"
  ↓ (drift report)

spawn: doc-keeper
  ↓
  "Fix the three drift items in the report"
  ↓ (reads each doc, edits, upserts)
```

### Onboarding a new vendor dependency

```
spawn: corpus-sync
  ↓
  "Crawl the LaunchDarkly docs so they're searchable locally"
  ↓ (confirms URL, runs crawl with --sitemap, reports pages)

spawn: doc-keeper
  ↓
  "Tag every LaunchDarkly doc with category=integrations"
  ↓ (iterates update_metadata over the crawled paths)
```

---

## Customization

### Switch models

Edit `model:` in the frontmatter. Supported aliases: `opus`, `sonnet`,
`haiku`. For cost-sensitive users, `context-loader` and `doc-explorer`
can run on `haiku` (the former already does).

### Add project-specific tools

Add to the `allowedTools:` list. Common additions:

- `Bash` — for project-specific shell (tests, builds, migrations)
- `Edit` / `Write` — for agents that modify files (doc-keeper
  already has these)
- `mcp__postgres__query` — if your project has a Postgres MCP server
  for schema introspection

### Restrict MCP server access

Add `allowedMcpServers: ["gnosis"]` to scope an agent to only talk to
gnosis-mcp (keeps it from wandering into other MCP servers).

### Scope-by-directory

For monorepos, point agents at a subtree:

```yaml
allowedPaths:
  - docs/**
  - src/**
```

---

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI or
  IDE extension (any MCP-capable client works in principle)
- gnosis-mcp server running (stdio, streamable-http, or sse)
- For write operations (doc-keeper, corpus-sync):
  `GNOSIS_MCP_WRITABLE=true`
- For embeddings: `pip install 'gnosis-mcp[embeddings]'`
- For web crawl: `pip install 'gnosis-mcp[web]'`

---

## Pair skills

The `skills/` folder has companion slash commands — one per common
workflow. They're designed to call the same MCP tools but with
structured CLI-style args:

| Skill | What it does |
|---|---|
| `/gnosis:setup` | First-time wizard: install → init-db → ingest → wire your editor |
| `/gnosis:ingest` | Bulk ingest (files, git, crawl) + re-ingest + prune |
| `/gnosis:tune` | Chunk-size sweep against your own golden query set |
| `/gnosis:search` | Keyword / hybrid / git-history search with formatted output |
| `/gnosis:manage` | Single-file CRUD (add, delete, update metadata, related) |
| `/gnosis:context` | Usage-weighted topic primer |
| `/gnosis:status` | Connectivity, schema, corpus health |

Copy both `agents/` and `skills/` — they work better together. Agents
own the reasoning; skills own the boilerplate.

---

## Minimal `.mcp.json`

Stdio transport (simplest, one server per editor session):

```json
{
  "mcpServers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

Streamable-HTTP (shared server, multiple editors/sessions):

```json
{
  "mcpServers": {
    "gnosis": {
      "type": "url",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Start the HTTP server separately:

```bash
gnosis-mcp serve --transport streamable-http --rest --watch ./docs
```

---

## v0.11 reminders

- Default `GNOSIS_MCP_CHUNK_SIZE` is now **2000 chars** (was 4000).
  Expect finer-grained chunks than older deployments.
- Cross-encoder reranking is **off by default and documented as a
  trap for dev docs** — the bundled MS-MARCO model lowers quality on
  technical documentation by ~27 nDCG@10. Don't enable without
  measuring against your own corpus via `/gnosis:tune full`.
- Hybrid search (`--semantic` on /gnosis:search) often produces
  identical rankings to keyword on vocabulary-matched corpora. Not a
  bug — it just means BM25 is already nailing it. See
  [bench-experiments](https://gnosismcp.com/doc/docs/bench-experiments-2026-04-18).
