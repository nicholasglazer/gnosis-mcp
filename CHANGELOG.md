# Changelog

All notable changes to gnosis-mcp are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0).

## [Unreleased]

### Added
### Changed
### Fixed
### Security

## [0.11.3] - 2026-04-19

### Removed
- **`llms.txt.tmpl` + `llms-full.txt.tmpl` + `scripts/render-llms.py`** and the corresponding `render-llms.py --check` CI step. Over-engineered for 4 trivial tokens; `bump-version.sh` now does in-place `sed` on `llms.txt` + `llms-full.txt`. Measured numbers (test count, MCP latency ms) stay maintainer-edited when benchmarks are re-run. One file per concept instead of two. Rationale: the template/rendered pair was added in v0.11.0 assuming more tokens would accumulate; they didn't, so it's just extra surface.
- **`.mcpregistry_github_token` + `.mcpregistry_registry_token`** — stale on-disk tokens from before v0.10.13's security hardening, which moved registry auth to GitHub Secrets. Files were gitignored but still on disk, confusing for anyone finding them. `.gitignore` entry dropped too (no longer needed).

### Changed
- **`.gitignore` narrowed from `.claude/` to `.claude/agent-memory/`**. Only per-session subagent notes are now ignored; a future `.claude/settings.json` or similar team-tooling config would be trackable without fighting the ignore. No behaviour change today (no such files exist), but removes a papercut for later.
- **`llms-install.md` restructured** to cover three install paths explicitly — Path A (Claude Code plugin marketplace, one command), Path B (manual copy-paste for cherry-picking agents/skills), Path C (MCP-server-only for any editor). Previously 202 lines of MCP-only editor snippets with zero plugin coverage; now 292 lines with the plugin path front-loaded as the recommended option. Single canonical install guide — `agents/README.md` and `skills/README.md` no longer duplicate setup boilerplate, they just link here.
- **`README.md` Claude Code Plugin table refreshed** — previously listed only 3 slash commands (`/search`, `/status`, `/manage`) out of the 8 we actually ship. Now covers all 8 skills plus the 5 subagents the plugin installs.

### Added
- **`/gnosis:eval` skill** (`skills/eval/SKILL.md`) — single-shot retrieval quality check that wraps `gnosis-mcp eval`, interprets the numbers in plain English (Hit@5 / MRR / nDCG@10 / Precision@5), and compares to a saved baseline stored at `~/.local/share/gnosis-mcp/eval-baseline.json`. Three modes: default (run + compare + recommend), `quick` (numbers only), `save` (lock current as new baseline), `diff` (compare without advising). Complements `/gnosis:tune` (which sweeps configurations); eval is the faster health-check.
- **Codeberg mirror automation** in `.github/workflows/publish.yml` — a new `mirror-codeberg` job pushes main + all tags to Codeberg on every tag release. Guarded so the workflow stays green when `CODEBERG_TOKEN` isn't set; enable by adding the secret plus optional `CODEBERG_REPO` / `CODEBERG_USER` repo variables.
- **PKGBUILD ↔ .SRCINFO source-URL drift check** in `scripts/check-versions.sh`. Catches the class of bug that slipped between v0.11.1 and v0.11.2, where the sha256-only sed fallback left `.SRCINFO` pointing at a content-hash PyPI path while PKGBUILD had been bumped to the predictable `/source/g/` form. Normalizes `$pkgver` in the comparison so baseline state passes.
- **`.claude-plugin/plugin.json` version-parity coverage**. The file was 5 minor versions stale (`0.6.0` while pyproject was `0.11.2`) because `bump-version.sh` never touched it. Now bumped in lockstep and gated by `check-versions.sh`.

### Changed
- **Workflow permissions** on the repo now allow GitHub Actions to create and approve pull requests. This lets the existing `pypi-resolve-and-arch-pr` job finally complete its last step — opening the PR with the computed Arch sha256 — so AUR packaging stays aligned without a manual branch merge.

### Fixed
- **Contact email unified to `info@nicgl.com`** across every metadata file. Previously: `pkg/arch/PKGBUILD` + `PKGBUILD-git` had an obsolete `nicholasglazer@protonmail.com`, and `marketplace.json` had a `nicholasglazer@gmail.com` that didn't match the SECURITY / CODE_OF_CONDUCT / CONTRIBUTING / pyproject canonicals. Added an `email` field to `.claude-plugin/plugin.json` as well. One email everywhere now.
- **`sqlite://` URL prefix now stripped before opening the DB file** (`sqlite_backend.py`). Previously `GNOSIS_MCP_DATABASE_URL=sqlite:///path/docs.db` (the format shown in `docs/config.md`, `llms-install.md`, and used by every `tests/bench/*.py` helper) was passed to `aiosqlite.connect()` verbatim — Linux treated the colon as a valid filename character and created a `sqlite:` turd-dir relative to the process cwd, with the actual DB buried inside. The server's `bench_real_corpus.py` runs had been quietly leaving `~/prod/gnosis-mcp/sqlite:/tmp/gnosis-real-*.db` behind for months. New helper `_sqlite_path_from_url()` normalizes `sqlite:///abs`, `sqlite:////abs`, `sqlite://:memory:`, and bare paths alike; regression test asserts no `sqlite:` directory appears in cwd.
- **Crawl now accepts `text/plain` and `text/markdown` responses** (`crawl.py`). Previously `fetch_page` silently returned `None` for any non-`text/html` content-type, which bubbled up as a misleading `[=] ... 304 Not Modified` log line and zero chunks ingested. This excluded the entire `llms-full.txt` pattern used by MCP, Anthropic docs, Vercel, and other LLM-ready single-file doc bundles. Plain-text bodies now flow through as pre-extracted markdown (trafilatura skipped). The `None`-means-304 ambiguity in the caller is also addressed — when a URL returns `None` without having a cache entry, the log now reads `unsupported response` instead of lying about a conditional request that never happened.

### Security

## [0.11.2] - 2026-04-19

### Fixed
- **Ruff lint + format failures on `main`** that gated the v0.11.1 publish workflow. `tests/bench/bench_beir.py` and `tests/bench/bench_sweep.py` had unused `import os` (F401) and a stray `f"..."` with no placeholders (F541). Eight files were also overdue for `ruff format`. All auto-fixable. Net effect of v0.11.1: same as v0.11.0 — Docker shipped, PyPI didn't. v0.11.2 is the first version to exercise PyPI + MCP Registry end-to-end.
- **CI trigger for `main` branch** (`.github/workflows/ci.yml`). Previous rule `branches-ignore: [main]` meant main pushes never ran lint/pytest; v0.11.0 and v0.11.1 both shipped broken because of regressions that CI would have caught on a PR. Switched to `branches: ["**"]` so CI runs on every push, closing the loophole.

## [0.11.1] - 2026-04-19

### Fixed
- **`.github/workflows/publish.yml` YAML parse error** in the `pypi-resolve-and-arch-pr` job introduced in v0.11.0. A `gh pr create --body "..."` argument spanned multiple lines and contained both a blank line and backtick-escaped inline code — that combination broke YAML's multiline-quoted-string scanner, so the workflow failed at parse time (0 s duration, no job logs) on every push since the job was added. Switched to `--body-file` with a heredoc. Net effect of v0.11.0: the Docker image published successfully but PyPI, MCP Registry, and the Arch-sums PR automation never ran. v0.11.1 is the first release that exercises those paths end-to-end.
- **`tests/test_local_embed.py` collection error** introduced in v0.11.0 by the ONNX filename fallback patch. The test module imported `_MODEL_FILES` which had been renamed to `_TOKENIZER_FILES` + `_ONNX_CANDIDATES`; pytest couldn't import the module at all, so 15 tests silently went uncollected (dropping the reported count from 632 to 617 without raising a red flag). CI on the release branch was path-filtered to `pyproject.toml` only, which let the regression slip past. Tests now updated to the new API shape; all 632 collect and the 627 non-PG tests pass.

## [0.11.0] - 2026-04-18

### Changed
- **Default chunk size lowered 4000 → 2000 chars** (`GNOSIS_MCP_CHUNK_SIZE`). Measured on a real 558-doc developer-docs corpus with 25 hand-written golden queries: 2000-char chunks sit on the peak nDCG@10 plateau (0.8702), up from 0.8416 at the old 4000-char default (+3 nDCG points, Hit@5 0.88 → 0.92). Existing corpora keep working; re-ingest with `--wipe` to regenerate at the new size. Full sweep in `docs/bench-experiments-2026-04-18.md`.
- **Documentation hardened on reranker guidance.** The bundled `[reranking]` cross-encoder remains off by default. New measurements on the same corpus: MiniLM rerank drops nDCG@10 by 27 points and adds 400× latency; BGE-reranker-v2-m3 drops nDCG@10 by 31 points and adds 2400× latency. Search skill now warns explicitly before enabling. Prose-trained rerankers fight reference-style docs; measure on your corpus before turning it on.

### Added
- **Release pipeline** (`scripts/bump-version.sh`, `scripts/release.sh`, `scripts/update-arch-sums.sh`, `scripts/render-llms.py`, `docs/releasing.md`). Single-command version bump across 13 files — pyproject, `__init__.py`, `server.json`, `marketplace.json`, `SECURITY.md`, `CHANGELOG.md`, `pkg/arch/PKGBUILD`, `pkg/arch/.SRCINFO`, `docs/rest-api.md`, `docs/show-hn.md`, `demo/hero.tape`, `skills/setup/SKILL.md`, `uv.lock`. Extended `scripts/check-versions.sh` now gates all seven version-bearing files in CI and on every parity check. `scripts/release.sh verify <X.Y.Z>` polls PyPI / GHCR / MCP Registry / GitHub / AUR after a tag push and reports which are live.
- **Post-release Arch-sums PR workflow**. A new job in `.github/workflows/publish.yml` polls PyPI until the new sdist resolves, computes the tarball sha256, and opens a PR with the PKGBUILD + `.SRCINFO` update. First-time AUR publish walkthrough in `docs/releasing.md` §8.
- **Template-rendered `llms.txt` / `llms-full.txt`**. Source lives in `llms.txt.tmpl` and `llms-full.txt.tmpl` with `{{VERSION}}` / `{{TEST_COUNT}}` / `{{MCP_MEAN_MS}}` / `{{MCP_P95_MS}}` tokens; CI gates the rendered output for drift.
- **Agents + skills refresh.** `agents/corpus-sync.md` (bulk ingest / prune / wipe / crawl / git-history lifecycle with playbooks), updated `agents/doc-keeper.md` (single-file CRUD lane), and rewritten skills: `skills/search/`, `skills/ingest/`, `skills/tune/`, `skills/manage/`. Users can drop these straight into `~/.claude/agents/` and `~/.claude/skills/`.
- **Benchmark experiments log** (`docs/bench-experiments-2026-04-18.md`): full chunk-size sweep (1000 → 4000 chars), reranker comparison table (keyword, MiniLM, BGE-v2-m3, mxbai-large), hybrid-vs-keyword on vocabulary-matched corpora, with raw numbers and methodology.
- **`tests/bench/bench_real_corpus.py --embed-model / --embed-dim` flags** — swap the embedder for A/B retrieval-quality shoot-outs against any model that ships an ONNX artefact on HuggingFace.
- **`GNOSIS_MCP_ALLOW_PRIVATE_CRAWL=true` env override** for the crawl SSRF guard — useful for local dev, CI, and Docker-internal testing. Mirrors the existing `GNOSIS_MCP_WEBHOOK_ALLOW_PRIVATE` pattern. Off by default.
- **ONNX filename fallback** in `local_embed.py` — tries `onnx/model_quantized.onnx` first, then `onnx/model.onnx`. Lets the embedder load any HF repo that ships either variant.
- **`/eval` short-answer tooling** exposed through the `gnosis-mcp eval` CLI and the `tune` skill — measures Hit@K / MRR / Precision@K on a user's own corpus in under a second.
- **Docker image** published to GHCR (`ghcr.io/nicholasglazer/gnosis-mcp`), multi-arch (linux/amd64, linux/arm64), built by `.github/workflows/docker.yml` on every tag push.
- **Landing site refresh** at [gnosismcp.com](https://gnosismcp.com): honest feature copy, fact-checked benchmark card, graph visualization driven by live `documentation_links` data, `llms.txt` + `llms-full.txt` served at the root for AI-assistant ingestion.
- **Rewritten demo GIFs.** `demo/demo-hero.gif` (440 KB) and `demo/demo-crawl.gif` (584 KB). Real commands only — no fake version echoes, no `pip install` during recording, no backgrounded-server noise. Source (VHS tape + staging scripts) lives in `.internal/demo-source/`.

### Fixed
- `llms.txt` and `llms-full.txt` now reflect the actual test count (632) and the current SDK version.
- CHANGELOG ordering: `[Unreleased]` stays at the top; `All notable changes…` preamble moved out of the release block so it doesn't get rolled into a version section on the next bump.

## [0.10.13] - 2026-04-17

### Security
- **Timing-safe Bearer token comparison** in REST API auth (`secrets.compare_digest`).
- **Webhook SSRF guard**: `GNOSIS_MCP_WEBHOOK_URL` now refuses private, loopback, link-local, multicast, and reserved addresses unless `GNOSIS_MCP_WEBHOOK_ALLOW_PRIVATE=true`.
- **HuggingFace model download**: enforced `https://huggingface.co/` origin assertion, SHA-256 checksum verification scaffolding for the bundled default model.
- **robots.txt cross-host redirect** now treated as disallow (prevents redirect-based spoofing).
- **Content size caps**: `upsert_doc` rejects content over `GNOSIS_MCP_MAX_DOC_BYTES` (default 50 MB); `search_docs` rejects queries over `GNOSIS_MCP_MAX_QUERY_CHARS` (default 10 000).
- **Dependency upper bounds** pinned on `mcp`, `aiosqlite`, `asyncpg`, `onnxruntime`, `tokenizers`, `numpy`, `sqlite-vec`, `httpx`, `trafilatura`, `docutils`, `pypdf` — major-version bumps can no longer slip in.

### Added
- **Typed relations** (`relations:` frontmatter block): documents can now declare semantic edge types beyond the flat `relates_to:` list. Supported types: `related`, `prerequisite`, `depends_on`, `summarizes`, `summarized_by`, `extends`, `extended_by`, `replaces`, `replaced_by`, `audited_by`, `audits`, `implements`, `implemented_by`, `tests`, `tested_by`, `example_of`, `references`. Unknown types warn and are skipped. Stored in the existing `relation_type` column; queryable via `get_related(relation_type=...)` and `get_graph_stats()`. No schema migration needed — `relation_type` column already existed.
- **CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md** for OSS community hygiene.
- **PR CI workflow** (`.github/workflows/ci.yml`): ruff + pytest on Python 3.11 & 3.12, SQLite backend green-gated, PostgreSQL backend + pgvector service container (allow-failure during backend parity ramp-up).
- **Version-parity CI gate** (`scripts/check-versions.sh`): fails the release workflow if `pyproject.toml` / `__init__.py` / `server.json` / `marketplace.json` drift.
- **Tag-vs-pyproject assertion** in `publish.yml` — a `v*` tag push whose name disagrees with `pyproject.toml` fails early.
- **End-to-end MCP protocol tests** (`tests/test_mcp_e2e.py`): spawn `gnosis-mcp` subprocess, drive it through stdio MCP, assert 9 tools + 3 resources + write/read roundtrip + `gnosis-mcp check` integration.
- **Three benchmark suites** in `tests/bench/`: `bench_search.py` (speed), `bench_rag.py` (retrieval quality — Precision@K, MRR, Hit Rate, keyword vs hybrid), `bench_mcp_e2e.py` (protocol round-trip latency).
- **`gnosis-mcp eval` CLI subcommand** — runs the retrieval-quality harness and prints Hit@K / MRR / Precision@K in ~1 s. Short answer to "show me the numbers".
- **`gnosis-mcp prune <path>`** — deletes DB chunks whose source file no longer exists on disk. Scoped to the given root so crawled URLs are untouched by default (`--include-crawled` to also prune them). `--dry-run` previews.
- **`gnosis-mcp ingest --prune`** — after ingest, prune stale docs in the same pass.
- **`gnosis-mcp ingest --wipe`** — nuke every document before re-ingesting (nuclear reset for re-organized knowledge folders).
- **`[reranking]` optional extra** with ONNX cross-encoder reranker (`onnx-community/ms-marco-MiniLM-L6-v2-ONNX`, 22 M params, Apache 2.0). Off by default; enable via `GNOSIS_MCP_RERANK_ENABLED=true` or the `rerank=true` tool parameter.
- **`GNOSIS_MCP_RRF_K`** env var to tune hybrid-search Reciprocal Rank Fusion (default 60, the canonical value).
- `/health` REST endpoint now exposes `search_stats` (total / misses / hybrid / keyword counters).
- **Benchmarks doc** (`docs/benchmarks.md`) with methodology, scale curve to 10 000 docs, RAG-native metrics, PostgreSQL reproduction steps, and regression gates.
- **Dependency floors bumped**: `mcp>=1.27`, `aiosqlite>=0.22`, `asyncpg>=0.30`, `onnxruntime>=1.22`, `tokenizers>=0.22`, `numpy>=2.0`, `sqlite-vec>=0.1.6`, `httpx>=0.28`, `trafilatura>=2.0`, `docutils>=0.22`, `pypdf>=5.0`. Upper bounds retained.
- **Pytest markers** (`sqlite_only`, `postgres_only`, `eval`, `bench`, `e2e`) registered in `pyproject.toml`.
- **`GNOSIS_MCP_CRAWL_EXTRACT_TIMEOUT_S`** (default 30 s) caps per-page trafilatura extraction.
- First-run guidance: `gnosis-mcp search` against an empty database now hints to run `gnosis-mcp ingest <path>` first.
- REST request logging middleware: method, path, status, duration_ms at INFO (skips `/health`).
- Windows install paths documented in `llms-install.md`.

### Changed
- **MCP protocol round-trip latency improved ~35 %** (13.3 ms → 8.7 ms mean, 24.4 ms → 13.0 ms p95) via `mcp` SDK upgrade to 1.27.
- Ingest format dispatch refactored to a registry (`_CONVERTERS` in `ingest.py`) — adding a new format is now a single map entry.
- Duplicate search-result dict construction in `server.py` extracted to `_format_search_result()` helper.
- Tests gate the publish workflow (`publish.yml`): ruff check + pytest must pass before PyPI upload.
- MCP Registry publish step now has explicit error handling, timeout, and binary integrity check.
- vec0 initialization failure is now fail-fast when `GNOSIS_MCP_EMBED_PROVIDER` is configured (silent degradation hid hybrid-search breakage).
- Resource error responses include exception type and a `hint` to run `gnosis-mcp check`.
- `_search_custom` PostgreSQL fallback narrowed to `asyncpg.UndefinedFunctionError`, `AmbiguousFunctionError`, `InvalidParameterValueError` (was catching every exception).

### Fixed
- **`/health` now bypasses Bearer auth** even when `GNOSIS_MCP_API_KEY` is set — monitoring probes and load balancers were previously broken by returning 401. Regression test added in `tests/test_rest_auth.py`.
- Documentation claim alignment: corrected test count, format count, and tool count across README, `llms.txt`, `llms-full.txt`, and `docs/show-hn.md`.
- README links to `llms-install.md` from the Quick Start section.
- `.coverage`, `htmlcov/`, `coverage.xml` added to `.gitignore`.
- Removed orphaned `demo.gif` (not referenced) and stray `sqlite:/` directory (CLI-misparse artefact).

## [0.10.12] - 2026-04-07

### Added
- **Enriched `get_related` tool**: Multi-hop traversal (`depth=1-3`), relation type filtering, and optional title/category enrichment via `include_titles`.
- **`get_graph_stats` tool**: Knowledge graph topology — orphans (disconnected docs), hubs (most connected), relation type distribution, edge/node counts.
- **Content link extraction**: `ingest` now parses `[text](path.md)` markdown links and `[[wikilinks]]` from body content, stored as `content_link` relation type.
- **`GET /api/graph/stats` REST endpoint**: Same functionality as the MCP tool.
- **`gnosis-mcp fix-link-types` CLI command**: Migrate existing git-history links from generic `relates_to` to proper `git_co_change` and `git_ref` types.

### Changed
- Git history ingest now uses `git_co_change` (cross-file) and `git_ref` (source file) relation types instead of generic `relates_to`.

## [0.10.11] - 2026-04-07

### Added
- **`get_context` tool**: Usage-weighted context loading — surfaces most-accessed documents for efficient session startup. Supports topic search enrichment, category filtering, and repository statistics.
- **Access tracking**: `search_access_log` table automatically records document access from `search_docs` (top 3 results) and `get_doc`. Fire-and-forget pattern, opt-out via `GNOSIS_MCP_ACCESS_LOG=false`.
- **`GET /api/context` REST endpoint**: Same functionality as the MCP tool, available when REST API is enabled.
- **`gnosis-mcp cleanup` CLI command**: Purge old access log entries (`--days N`, default 90).

## [0.10.10] - 2026-04-07

### Added
- Example agents for Claude Code: doc-explorer, doc-keeper, doc-reviewer, context-loader (`agents/` directory)
- `search_git_history` section in search skill with `--git` flag
- Git history and web crawl sections in setup skill
- All optional install extras documented in setup skill (`[embeddings]`, `[web]`, `[formats]`)

### Fixed
- Skills: updated tool count from 6 to 7 across all skills (search_git_history was missing)
- Search skill: corrected hybrid search note — SQLite also supports hybrid via sqlite-vec RRF
- Manage skill: added missing `audience` parameter to upsert_doc and update_metadata examples
- CLAUDE.md: corrected tool count from 6 to 7 in architecture diagram

### Changed
- Updated deps: mcp 1.27.0, onnxruntime 1.24.4, numpy 2.4.4, ruff 0.15.9

## [0.10.9] - 2026-04-07

### Fixed
- `has_column()` on PostgreSQL: switch from `information_schema.columns` to `pg_catalog.pg_attribute` — fixes `upsert_doc` NotNullViolationError on Supabase and other PostgreSQL deployments where role permissions filter information_schema visibility. This was the actual root cause of the content_hash bug that v0.10.8 attempted to fix.

## [0.10.8] - 2026-04-01

### Fixed
- `upsert_doc` MCP tool: compute content_hash (SHA-256) on insert, fixing NotNullViolationError on PostgreSQL deployments with NOT NULL constraint on content_hash column
- SQLite `upsert_doc`: same content_hash fix, with `has_column()` detection for backwards compatibility

## [0.10.7] - 2026-03-24

### Added
- Comparison table in README: gnosis-mcp vs Context7 vs Grounded Docs vs mcp-local-rag — feature-by-feature positioning
- Submitted to tolkonepiu/best-of-mcp-servers directory (knowledge-and-memory category)

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
