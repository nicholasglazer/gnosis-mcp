# Example Agents for Gnosis MCP

Ready-to-use agent definitions for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Copy these into your project's `.claude/agents/` directory and they'll work with your Gnosis MCP knowledge base.

## Quick Setup

```bash
# Copy agents to your project
cp -r agents/*.md /path/to/your/project/.claude/agents/

# Make sure Gnosis MCP is configured in your .mcp.json
# (stdio transport — simplest)
cat .mcp.json
{
  "mcpServers": {
    "gnosis": {
      "command": "gnosis-mcp",
      "args": ["serve"]
    }
  }
}
```

## Available Agents

| Agent | Model | Purpose | Tools |
|-------|-------|---------|-------|
| **doc-explorer** | sonnet | Search and navigate docs | read-only |
| **doc-keeper** | sonnet | Index, update, clean up docs | read+write |
| **doc-reviewer** | sonnet | Audit docs against code | read-only |
| **context-loader** | haiku | Fast context priming | read-only |

## How They Work

### doc-explorer
Search your knowledge base before diving into code. Finds relevant docs, follows link graphs, and cross-references with git history.

```
# In Claude Code, the Agent tool spawns it automatically:
"Search the docs for how authentication works"
→ Agent uses mcp__gnosis__search_docs + get_doc + get_related
```

### doc-keeper
Keeps your knowledge base in sync with your codebase. Index new docs, update metadata, remove obsolete content.

```
"Index all the new guides I just wrote in docs/guides/"
→ Agent reads files, upserts to Gnosis, verifies indexing
```

### doc-reviewer
Pre-release doc audit. Finds stale references, missing features, and outdated examples by comparing docs against actual code.

```
"Review all docs related to the billing system"
→ Agent searches, reads docs, greps code, produces a drift report
```

### context-loader
Lightweight haiku agent that primes your context window with relevant docs before you start working. Uses `get_context` for usage-weighted summaries, then drills into specific docs if needed. Keeps token usage low.

```
"Load context about the database schema"
→ Agent calls get_context(topic="database schema"), returns a 200-word summary
```

## Customization

### Change the model
Edit the `model:` field in the frontmatter. Options: `opus`, `sonnet`, `haiku`.

### Add project-specific tools
Add tools to `allowedTools:` list. Common additions:
- `Bash` — for running project-specific commands
- `Edit` / `Write` — for agents that modify files
- `mcp__postgres__query` — for agents that need database access

### Restrict MCP access
Add `allowedMcpServers:` to limit which MCP servers an agent can use:
```yaml
allowedMcpServers:
  - gnosis
```

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI or IDE extension
- Gnosis MCP server running (any transport: stdio, SSE, or HTTP)
- Documents indexed via `gnosis-mcp ingest ./docs/`
