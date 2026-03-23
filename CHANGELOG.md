# Changelog

All notable changes to gnosis-mcp are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0).

## [0.10.6] - 2026-03-23

### Fixed
- MCP Registry publish pipeline: `server.json` transport field was an array (invalid) — changed to single object per schema. This fixes 17 consecutive CI failures since v0.7.3 and restores registry updates.

## [0.10.5] - 2026-03-23

### Added
- Always-on `/health` endpoint for HTTP transports (streamable-http, sse) — no longer requires `--rest` flag. Returns `{"status": "ok", "version": "...", "transport": "..."}`. Full REST API (`/api/*`) still requires `--rest`.

## [0.10.4] - 2026-03-22

### Added
- Transport guide in README: explains stdio vs HTTP tradeoffs, why stateful servers benefit from HTTP sharing, and how to configure multi-session setups

## [0.10.3] - 2026-02-23

### Fixed
- Custom search function disambiguation: add explicit `NULL::vector` cast for `p_embedding` parameter when no query embedding is provided, fixing `AmbiguousFunctionError` with PostgreSQL databases that have multiple overloaded search function signatures

## [0.10.2] - 2026-02-23

### Fixed
- CORS preflight now works when API key auth is enabled (middleware ordering fix: CORS outermost, auth innermost)
- Added test coverage for `/api/docs/{path}/related` endpoint
- Removed no-op `TYPE_CHECKING` block from `rest.py`
- `--rest` with stdio transport now logs a warning instead of silently ignoring

## [0.10.1] - 2026-02-23

### Changed
- Documentation: added REST API usage to README, llms.txt, llms-full.txt, CLAUDE.md

## [0.10.0] - 2026-02-23

### Added
- **REST API**: Native HTTP endpoints alongside MCP — `GET /api/search`, `/api/docs/{path}`, `/api/docs/{path}/related`, `/api/categories`, `/health`
- Enable via `--rest` flag on `serve` or `GNOSIS_MCP_REST=true` env var
- Optional CORS support via `GNOSIS_MCP_CORS_ORIGINS` (comma-separated origins or `*`)
- Optional API key auth via `GNOSIS_MCP_API_KEY` (Bearer token in Authorization header)
- `create_rest_app()` factory for standalone REST app
- `create_combined_app()` factory for MCP + REST on same port
- Hybrid search auto-embeds queries when local provider is configured

## [0.9.13] - 2026-02-23

### Added
- **Search benchmark script**: `tests/bench/bench_search.py` — automated QPS, latency percentiles, hit rate measurement
- **Performance section in README**: ~9,800 QPS (100 docs), ~3,500 QPS (500 docs), p50 under 0.25ms
- Performance data added to `llms.txt` and `llms-full.txt`
- Install size noted: ~23MB with `[embeddings]`, ~5MB base
- Test count: 550+ tests, 10 eval cases (90% hit rate, 0.85 MRR)

## [0.9.12] - 2026-02-23

### Added
- **Cross-file commit graph links**: When a commit touches files A, B, C, their git-history docs now link to each other via `relates_to`
- `_build_cross_file_links()` pure function for computing shared-commit relationships
- Links created automatically after `ingest-git` completes, enriching `get_related` results

## [0.9.11] - 2026-02-23

### Added
- **Git history eval cases**: 5 new eval cases for commit messages, author emails, and file changes
- 4 sample git-history documents added to eval fixture (auth, db, tests, pyproject)
- Eval harness now covers 10 cases total: 90% hit rate, 0.85 MRR on sample corpus

## [0.9.10] - 2026-02-23

### Added
- **`search_git_history` MCP tool**: Dedicated tool for searching git commit history with post-filters
- Scoped to `git-history` category automatically — no need to pass `category` parameter
- Filters: `author` (name/email substring), `since`, `until`, `file_path` (path substring)
- Over-fetches 3x then post-filters for accurate author/file matching

## [0.9.9] - 2026-02-23

### Added
- **`--author` filter for `ingest-git`**: Filter commits by author name or email (e.g. `--author Alice`)
- **`--until` filter for `ingest-git`**: End date filter complementing existing `--since` (e.g. `--until 2026-02-20`)

## [0.9.8] - 2026-02-23

### Added
- **Author email in git history**: `git log` now captures `%ae` (author email) alongside `%an` (author name)
- Rendered markdown includes `Author: Name <email>` for better searchability
- `GitCommit` dataclass gains `author_email` field

## [0.9.7] - 2026-02-23

### Fixed
- **Empty query handling**: `search()` now validates input — empty/whitespace-only queries return empty list with warning log
- **File path search fallback**: When FTS5 returns 0 results and query contains `/` or `.`, falls back to `file_path LIKE` search
- `search_docs` MCP tool returns descriptive error for empty queries instead of silent empty result

## [0.9.6] - 2026-02-23

### Added
- **`--force` flag for `ingest-git`**: Re-ingest all files ignoring content hash, matching `ingest --force` behavior

## [0.9.5] - 2026-02-23

### Fixed
- **RST `include` directive crash**: `_convert_rst()` now disables `file_insertion_enabled` and `raw_enabled` in docutils settings
- RST files with `.. include::` or `.. raw::` directives no longer crash ingestion
- Added `except Exception` fallback that returns raw text with warning log on any docutils failure

## [0.9.4] - 2026-02-23

### Changed
- **Title boosting in FTS5**: `bm25()` now weights title column 10x over content column
- Searches matching a document's title rank significantly higher than content-only matches
- SQLite backend only (PostgreSQL uses ts_rank with different weight mechanism)

## [0.9.3] - 2026-02-23

### Added
- **Contextual chunk headers**: Embedding text now includes `"Document: {path} | Section: {title}"` prefix
- Embeddings capture hierarchical document context, improving retrieval accuracy for ambiguous queries
- `contextual_header()` pure function exported from `embed.py`
- `get_pending_embeddings()` now returns `title` and `file_path` alongside `id` and `content`
- Re-embed existing docs to benefit: `gnosis-mcp embed --provider local`

## [0.9.2] - 2026-02-23

### Added
- **Query logging**: Every `search_docs` call logs query, mode (keyword/hybrid), result count, top result path, score, and category
- **Search stats counters**: In-memory `_search_stats` dict tracks total searches, misses (zero results), and search mode breakdown
- Enables search quality monitoring: watch for rising miss rate or declining scores

## [0.9.1] - 2026-02-23

### Added
- **Search quality eval harness**: `tests/eval/` with Precision@K, MRR, and Hit Rate metrics
- JSON-driven test cases (`tests/eval/cases.json`) — add query-answer pairs to measure retrieval quality
- Baseline eval: 5 cases, 100% hit rate on sample docs
- Runs as part of `pytest tests/eval/ -v` — no extra dependencies

## [0.9.0] - 2026-02-23

### Added
- **Git history ingestion**: `gnosis-mcp ingest-git <repo-path>` converts commit history into searchable markdown documents
- Commit messages, authors, dates, and file associations parsed from `git log` via subprocess (zero new deps)
- One markdown document per file, each commit as an H2 section — flows through existing chunk/embed/search pipeline
- Stored as `git-history/<file-path>` with category `git-history` for scoped searches
- Auto-linking to source file paths via `relates_to` graph
- Content hashing for incremental re-ingest (skips files with unchanged history)
- CLI flags: `--since`, `--max-commits`, `--include`, `--exclude`, `--dry-run`, `--embed`, `--merges`
- New `src/gnosis_mcp/parsers/` package for non-file ingest sources
- 48 new tests (pure function + integration with temp git repos)

## [0.8.4] - 2026-02-22

### Changed
- README restructure: funnel layout (hook → proof → features → install)
- Added before/after framing section ("Without a docs server" / "With Gnosis MCP")
- Replaced prose "Why use this" with scannable feature bullets
- Wrapped CLI reference, ingestion details, architecture in collapsible sections
- Added PyPI monthly downloads badge
- Improved tagline: "Turn your docs into a searchable knowledge base for AI agents"
- Trimmed visible content from 334 to 290 lines while preserving all information

## [0.8.3] - 2026-02-22

### Fixed
- README readability: rewrote intro sections, collapsed editor integrations
- Factual errors: transport values, DATABASE_URL naming, hybrid search scope
- llms.txt DATABASE_URL consistency

## [0.8.2] - 2026-02-22

### Fixed
- **SECURITY**: SSRF protection — blocks private/internal IPs (127.x, 10.x, 192.168.x, ::1, metadata endpoints) and checks redirect targets
- **SECURITY**: XML size limit (10 MB) in sitemap parser to prevent billion-laughs-style attacks
- **SECURITY**: Response size guard (50 MB) in `fetch_page` to prevent memory exhaustion
- **SECURITY**: Cache file written with 0o600 permissions (owner-only read/write)
- **BUG**: `asyncio.CancelledError` no longer swallowed in `_crawl_single` — properly re-raised (Python 3.11+ treats it as `Exception` subclass)
- **BUG**: `save_cache` moved to `finally` block — cache data preserved even on errors or cancellation
- Atomic cache writes using `tempfile.mkstemp` + `os.replace` — no corruption on crash
- `asyncio.gather` uses `return_exceptions=True` — single task failure no longer aborts all tasks
- robots.txt parsed once per crawl session (`RobotFileParser` reused), not re-parsed per URL
- Nested sitemap index fetches now run in parallel via `asyncio.gather`
- BFS discovery respects `max_urls` cap on queue size (prevents unbounded memory growth)
- Crawl depth clamped to max 10 in `CrawlConfig.__post_init__`
- Debug log on robots.txt fetch failure (was silent `pass`)

### Added
- `CrawlAction` StrEnum for type-safe action values (`crawled`, `unchanged`, `skipped`, `error`, `blocked`, `dry-run`)
- `_is_private_host()` SSRF protection function
- `_parse_robots()` for one-time robots.txt parsing
- `TYPE_CHECKING` annotations for `httpx.AsyncClient`, `DocBackend`, `GnosisMcpConfig`
- `Counter` usage in CLI `cmd_crawl` for cleaner action counting
- 30+ new tests: SSRF, CancelledError, depth clamping, atomic writes, cache permissions, BFS cap, StrEnum, oversized responses

## [0.8.1] - 2026-02-22

### Fixed
- `extract_content()` now runs trafilatura in a thread pool (`run_in_executor`) to avoid blocking the event loop during CPU-bound HTML extraction
- BFS discovery uses `collections.deque` instead of `list.pop(0)` — O(1) popleft vs O(n) shift
- Nested sitemap index detection simplified from fragile double-negative to `len(nested) == len(all)`
- Silent `except: pass` on link insertion replaced with `log.debug()` for troubleshootability

### Added
- `--max-urls` flag (default: 5000) caps discovered URLs to prevent runaway memory on large sitemaps

## [0.8.0] - 2026-02-22

### Added
- **Web crawl for documentation sites**: `gnosis-mcp crawl <url>` ingests docs from the web
- Sitemap.xml discovery (`--sitemap`) and BFS link crawling (`--depth N`)
- robots.txt compliance — respects `Disallow` rules automatically
- ETag/Last-Modified HTTP caching for incremental re-crawl (304 Not Modified)
- URL path filtering with `--include` and `--exclude` glob patterns
- Dry run mode (`--dry-run`) to discover URLs without fetching
- Force re-crawl (`--force`) ignoring cache and content hashes
- Post-crawl embedding (`--embed`) for hybrid semantic search
- Rate-limited concurrent fetching (5 concurrent, 0.2s delay by default)
- New optional dependency extra: `pip install gnosis-mcp[web]` (httpx + trafilatura)
- Crawl cache at `~/.local/share/gnosis-mcp/crawl-cache.json`
- Crawled pages stored with URL as `file_path`, hostname as `category`

## [0.7.13] - 2026-02-20

### Fixed
- PostgreSQL multi-word search now uses OR (was AND) — parity with SQLite v0.7.9 fix
- Added `content_hash` column to PostgreSQL DDL for new installations

### Added
- E2E comparison test script for SQLite vs PostgreSQL backend parity
- 21 new unit tests: `ingest_path`, `diff_path`, links, highlights, config defaults, PG OR query
- Test suite now at 300+ tests

## [0.7.12] - 2026-02-20

### Added
- Optional RST support: `pip install gnosis-mcp[rst]` (docutils)
- Optional PDF support: `pip install gnosis-mcp[pdf]` (pypdf)
- Combined `[formats]` extra: `pip install gnosis-mcp[formats]`
- Dynamic extension detection: `.rst` and `.pdf` auto-enabled when deps installed

## [0.7.11] - 2026-02-20

### Added
- GitHub Releases: CI now creates GitHub releases with auto-generated notes
- Ingest progress: `[1/N]` counter in log output during file ingestion

## [0.7.10] - 2026-02-20

### Added
- CSV export format: `gnosis-mcp export -f csv`
- `gnosis-mcp diff` command: show new/modified/deleted files vs database state

## [0.7.9] - 2026-02-20

### Changed
- FTS5 multi-word search now uses OR instead of implicit AND for broader matching
- BM25 ranking still puts multi-match results first

## [0.7.8] - 2026-02-20

### Fixed
- `GNOSIS_MCP_CHUNK_SIZE` env var now passed to `chunk_by_headings()` (was parsed but ignored)

### Added
- `--force` flag for `gnosis-mcp ingest` to re-ingest unchanged files

## [0.7.7] - 2026-02-20

### Changed
- Replaced `huggingface-hub` dependency with stdlib `urllib.request` (~60 lines)
- Fixed CI release pipeline: combined auto-tag + publish into single `publish.yml`

### Removed
- `huggingface-hub` from `[embeddings]` extra (5 → 4 optional deps)

## [0.7.6] - 2026-02-20

### Added
- Multi-format ingestion: `.txt`, `.ipynb`, `.toml`, `.csv`, `.json` (stdlib only, zero extra deps)
- Each format auto-converted to markdown for chunking

## [0.7.5] - 2026-02-20

### Added
- Streamable HTTP transport (`--transport streamable-http`)
- `GNOSIS_MCP_HOST` and `GNOSIS_MCP_PORT` env vars
- `--host` and `--port` CLI flags for `serve` command

## [0.7.4] - 2026-02-20

### Changed
- Smart recursive chunking: splits by H2 → H3 → H4 → paragraphs
- Never splits inside fenced code blocks or tables

## [0.7.3] - 2026-02-20

### Added
- Frontmatter `relates_to` link extraction (comma-separated and YAML list)
- Links stored in `documentation_links` table, queryable via `get_related`

## [0.7.2] - 2026-02-20

### Added
- Search result highlighting: `<mark>` tags in FTS5 snippets (SQLite), `ts_headline` (PostgreSQL)

## [0.7.1] - 2026-02-20

### Added
- File watcher: `--watch` flag for `gnosis-mcp serve` auto-re-ingests on file changes
- Auto-embed on file change when local provider configured

## [0.7.0] - 2026-02-19

### Added
- Local ONNX embeddings via `[embeddings]` extra (onnxruntime + tokenizers + numpy)
- sqlite-vec hybrid search with Reciprocal Rank Fusion (RRF)
- `gnosis-mcp embed` CLI command for batch embedding backfill
- `--embed` flag on `ingest` and `search` commands
- Auto-embed queries when local provider configured (MCP server)

## [0.6.3] - 2026-02-18

### Added
- VS Code Copilot and JetBrains editor setup docs

## [0.6.2] - 2026-02-18

### Added
- MCP Registry badge and automated registry publish in CI

## [0.6.1] - 2026-02-18

### Added
- MCP Registry verification tag and `server.json`

## [0.6.0] - 2026-02-17

### Added
- SQLite as zero-config default backend (no PostgreSQL required)
- FTS5 full-text search with porter stemmer
- XDG-compliant default path (`~/.local/share/gnosis-mcp/docs.db`)
- `gnosis-mcp check` command for health verification

## [0.5.0] - 2026-02-16

### Added
- Embedding support: openai, ollama, custom providers
- Hybrid search (keyword + cosine similarity) on PostgreSQL
- Demo GIF in README

## [0.4.0] - 2026-02-15

### Changed
- Rebranded from stele-mcp to gnosis-mcp
- Published to PyPI
- Added configurable tuning knobs via env vars

## [0.3.0] - 2026-02-14

### Added
- Structured logging
- `get_doc` max_length parameter
- Safer frontmatter parsing

## [0.2.0] - 2026-02-13

### Added
- Resources (`gnosis://docs`, `gnosis://categories`)
- Write tools (upsert, delete, update_metadata)
- Multi-table support (PostgreSQL)
- Webhook notifications

## [0.1.0] - 2026-02-12

### Added
- Initial release: PostgreSQL backend, search_docs tool, ingest command
