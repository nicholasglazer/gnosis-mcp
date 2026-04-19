# Skills for gnosis-mcp

Copy-paste slash commands for [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
and other MCP clients that support the `skills/` folder convention.
Each skill bundles a workflow that would otherwise require the user to
memorise which `mcp__gnosis__*` tool to call with which arguments.

Pair them with the agents in `../agents/` — agents own the reasoning,
skills own the boilerplate.

---

## Quick setup

```bash
# From a clone of github.com/nicholasglazer/gnosis-mcp:
cp -r skills/* /path/to/your/project/.claude/skills/
cp   agents/*.md /path/to/your/project/.claude/agents/
```

Restart your MCP client and the commands become available.

---

## The roster

| Slash command | What it does | Paired agent |
|---|---|---|
| [`/gnosis:setup`](setup/SKILL.md) | First-time wizard: install → init-db → ingest → wire your editor | — |
| [`/gnosis:ingest`](ingest/SKILL.md) | **Bulk** ingest (files, git history, web crawl) + re-ingest + prune | `corpus-sync` |
| [`/gnosis:tune`](tune/SKILL.md) | Chunk-size **sweep** to find the optimum for your corpus | — |
| [`/gnosis:eval`](eval/SKILL.md) | Single-shot retrieval quality check (Hit@5 / MRR / nDCG) + regression gate | — |
| [`/gnosis:search`](search/SKILL.md) | Keyword / hybrid / git-history search, formatted | `doc-explorer` |
| [`/gnosis:manage`](manage/SKILL.md) | **Single-file** CRUD (add, delete, update metadata, related) | `doc-keeper` |
| [`/gnosis:context`](context/SKILL.md) | Usage-weighted topic primer for session startup | `context-loader` |
| [`/gnosis:status`](status/SKILL.md) | Connectivity, schema, corpus health diagnostic | — |

---

## Decision table — which skill do I run?

| I want to… | Use |
|---|---|
| Install gnosis-mcp and get my docs indexed | `/gnosis:setup` |
| Index new/changed docs | `/gnosis:ingest <path>` |
| Index my git commit history | `/gnosis:ingest git <repo>` |
| Index a vendor website | `/gnosis:ingest crawl <url>` |
| Clean up after a folder reorganisation | `/gnosis:ingest <path> --prune` |
| Nuke and rebuild everything | `/gnosis:ingest <path> --wipe` |
| Find out what chunk size is best for my corpus | `/gnosis:tune` |
| Search docs from the command line | `/gnosis:search <query>` |
| Add / delete / retag one specific doc | `/gnosis:manage ...` |
| Prime my session with the docs that matter most | `/gnosis:context [topic]` |
| Diagnose why something seems broken | `/gnosis:status [diag]` |

---

## How skills and agents compose

Skills are useful when you want to **do one thing cleanly** — a
single well-known workflow, structured args, predictable output.

Agents are useful when you want to **reason about a task** — "find
docs relevant to X, corroborate with code, summarise". Agents call
the same MCP tools, just with more autonomy.

Common pattern:

```
You:  /gnosis:setup ./docs
      (skill — wires everything up)

You:  @context-loader prime me on our billing system
      (agent — reasons about what "prime" means in this context)

You:  /gnosis:search stripe webhook idempotency
      (skill — direct keyword search)

You:  @doc-explorer how does our Shopify sync retry on failure?
      (agent — searches, reads, corroborates with source code)

You:  /gnosis:ingest ./docs --prune
      (skill — re-ingests after reorganising)
```

---

## Requirements

Same as the agents:

- gnosis-mcp installed (`pip install gnosis-mcp`)
- MCP server configured in your client's `.mcp.json`
- For write-capable skills (`/gnosis:manage`, `/gnosis:ingest`):
  `GNOSIS_MCP_WRITABLE=true` on the server process
- For `/gnosis:tune` and embedding-based flows:
  `pip install 'gnosis-mcp[embeddings]'`
- For `/gnosis:ingest crawl`: `pip install 'gnosis-mcp[web]'`

---

## Customisation

All skills accept `$ARGUMENTS` — whatever the user typed after the
slash command. They parse it themselves (single positional, flags,
key-value pairs). Feel free to edit any `SKILL.md` to tune the output
format to your team's preferences.

Each skill's frontmatter:

```yaml
---
name: ingest
description: Populate the gnosis-mcp knowledge base...
disable-model-invocation: true   # skill runs only when explicitly invoked
---
```

`disable-model-invocation: true` is set on mutating skills (ingest,
manage) so they don't run accidentally when a model decides it
"sounds relevant". The user always has to type the command.

---

## v0.11 reminders

- **Chunk size** defaults to 2000 chars — based on the Feb 2026 sweep
  on a real dev-docs corpus. Tune per-corpus with `/gnosis:tune`.
- **Cross-encoder reranker** is off by default and the docs actively
  warn against enabling on developer documentation — it drops nDCG by
  ~27 points on our corpus. Opt in only after `/gnosis:tune full`
  confirms it helps *yours*.
- **Hybrid search** is available but on vocabulary-matched corpora
  (typical dev docs), it produces the same top-10 as keyword. Not a
  bug; hybrid shines on paraphrase-heavy domains. Leave it off if
  your tune results show no lift.
