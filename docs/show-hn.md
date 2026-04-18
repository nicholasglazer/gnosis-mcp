# Show HN: Gnosis MCP – Zero-config documentation server for AI coding agents

**Link:** https://github.com/nicholasglazer/gnosis-mcp

---

**Top comment:**

I built gnosis-mcp because every AI coding assistant I use (Claude Code, Cursor, Windsurf) has the same problem: it can read files but can't search documentation efficiently. You either paste docs into context (wastes tokens), point it at URLs (hallucination risk), or hope the LLM's training data is fresh enough. None of these scale when you have 200+ internal docs, vendor references, and guides.

gnosis-mcp is an MCP server that indexes your documentation into a searchable database. Install, point it at a directory, it chunks and indexes everything. Your AI agent gets `search_docs`, `get_doc`, and `get_related` tools — semantic search over your actual docs instead of guessing.

**Zero config, two direct dependencies.** `pip install gnosis-mcp && gnosis-mcp serve --watch ~/docs`. That's it. SQLite database at `~/.local/share/gnosis-mcp/docs.db`. Two direct runtime deps (`mcp` and `aiosqlite`) pull in ~30 transitive from the MCP SDK (async runtime + protocol handling). No Docker, no Postgres, no API keys, no vector database to set up.

**Local embeddings with no API key.** Install the `[embeddings]` extra and gnosis downloads an ONNX model (~50MB) via stdlib `urllib`. Hybrid search uses Reciprocal Rank Fusion to merge BM25 keyword matches with vector similarity. No OpenAI key, no network calls during search. Runs on CPU.

**Smart chunking.** Splits by H2 headings, falls back to H3/H4 for oversized sections, then paragraphs. Never splits inside fenced code blocks or tables. Content hashing skips unchanged files on re-ingest.

**What it indexes:** Markdown, plain text, Jupyter notebooks, TOML, CSV, JSON, and optionally reStructuredText and PDF. Also crawls websites (sitemap discovery, robots.txt, ETag caching) and indexes git history.

**Scales up when needed.** Swap SQLite for PostgreSQL with `DATABASE_URL=postgresql://...` — gets you pgvector HNSW indexes, tsvector full-text search, and multi-table UNION ALL queries. Same tool API, same code.

**Document graph.** Add `relates_to` in YAML frontmatter and `get_related` returns bidirectional links. Your AI agent can navigate from a guide to its related API reference, architecture doc, or config file.

**REST API.** `gnosis-mcp serve --rest` exposes `/api/search`, `/api/docs/{path}`, `/api/categories` alongside the MCP transport. CORS + Bearer auth configurable. Use it from dashboards, CI, or non-MCP clients.

Numbers: v0.10.13, 601 tests, 8 input formats (6 built-in, 2 optional), 9 MCP tools, 3 MCP resources, SQLite + PostgreSQL backends, file watcher with auto-re-ingest.

How I use it: I have ~558 docs (internal guides, vendor references, architecture decisions, runbooks) indexed. Claude Code searches them via MCP instead of me pasting context. When I update a doc, the file watcher re-indexes automatically. On that real corpus we measure Hit@5 = 0.92 with keyword-only search at 7 ms p95.

Compared to alternatives: Context7 is a hosted shortcut for public library docs — convenient, but queries leave your machine and you can't add private docs. gnosis-mcp ships its own crawler so the same vendor docs land in your local SQLite alongside private docs, git history, and runbooks. One index, all local, no API keys.

`pip install gnosis-mcp` — PyPI, MIT license. Works with any MCP-compatible client (Claude Code, Claude Desktop, Cursor, Windsurf, etc.)
