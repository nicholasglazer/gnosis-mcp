# Changelog

All notable changes to gnosis-mcp are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0).

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
