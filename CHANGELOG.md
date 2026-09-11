# Changelog

All notable changes to gnosis-mcp are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0).

## [Unreleased]

### Added
### Changed
### Fixed
### Security

## [0.17.5] - 2026-09-11

### Added

### Changed

### Fixed

- **A section's own heading was not indexed once the section grew past the
  chunk size.** `_split_section_by_subheadings` began its chunks at the first
  sub-heading, so `content[:first_match]` — the parent heading and every
  paragraph introducing the sub-sections — became no chunk at all. The effect
  was invisible in the obvious check: the corpus still answered questions about
  the section's _contents_, yet a search phrased as the section's own name
  returned nothing, because no chunk contained that heading. It took a document
  written, ingested, embedded, and still unfindable by any phrasing to surface
  it. Measured old-vs-new chunking of the knowledge root: **141 of 245 ingested
  files, 1035 chunks** of heading and intro prose restored. The fix mirrors the
  document-level preamble chunk one level down, at every sub-heading level, and
  is covered by `test_h2_head_and_intro_before_first_h3_are_retained`.

### Security

## [0.17.4] - 2026-09-11

### Added

- **`gnosis-mcp usage`** — what this corpus was asked, what it served, and what
  it could not answer, over a window (`--days`, default 30): calls, misses,
  documents served, indexed documents no query has ever surfaced, and the split
  by tool, by client, and per document. `--json` emits the whole report.
- **A missed search is now a logged row.** When `search_docs` matches nothing it
  is recorded with an empty `file_path` — the index saying "nothing here", with
  the query that asked. `usage` ranks misses; every reader of the ledger that
  treats rows as documents (`get_top_accessed`, `get_context`) skips them.

### Changed

### Fixed

- **Postgres access logs silently lacked client and token attribution.**
  `search_access_log` was created without `tokens_returned`, `tokens_baseline`
  or `client`, and `CREATE TABLE IF NOT EXISTS` cannot add a column to a table
  that already exists — so on any Postgres install the ledger kept logging
  without them, `savings` reported zeros, and `doctor`'s per-client evidence
  could never fill in. The DDL now carries the columns and `init-db` retrofits
  them onto an existing table (`ADD COLUMN IF NOT EXISTS`), mirroring what
  SQLite already did.
- `scripts/update-arch-sums.sh` now polls for the PyPI sdist instead of fetching
  once. On 0.17.3 the single fetch 404'd against a file CDN that was still
  replicating, the release job failed, and the Arch sha pull request was never
  opened.

### Security

## [0.17.3] - 2026-09-11

Files that live on disk but shouldn't be searchable can now be excluded at
ingest time — and an exclude added later actually removes what was already
indexed.

### Added

- **`GNOSIS_MCP_INGEST_EXCLUDE`** — comma-separated root-relative path prefixes
  (`.internal/audit-logs/` excludes a directory, `llms-full.txt` one file) that
  `ingest`, `diff` and `prune` skip. `prune` treats an excluded file as _not on
  disk_, so documents indexed before the exclude was configured are deleted on
  the next prune instead of staying searchable forever — the startup scan
  skips them from then on, so nothing else would ever revisit those rows.
- **The watcher prunes when a tracked file is deleted.** Previously a deleted
  file kept its chunks until someone ran `prune` by hand.

### Changed

### Fixed

### Security

## [0.17.2] - 2026-09-11

`get_context` answered with the wrong search — or none at all — when you gave
it a topic.

### Fixed

- **`get_context` with a `topic` ran keyword-only search** (MCP tool and
  `GET /api/context`), so a natural-language topic — the way the argument is
  documented — matched no tsvector terms and returned `[]`. Both paths now
  auto-embed the topic into `query_embedding` exactly as `search_docs` /
  `GET /api/search` do, keeping the same degrade-to-keyword behaviour when the
  embeddings extra or model is unavailable.

## [0.17.1] - 2026-09-11

A one-bug patch. `get_context` had been failing on Postgres for every caller
since 0.10.11, and nothing said so: the tool returned an error with no hint at
the cause, the REST endpoint answered 500, and the CLI's own access-log purge
failed the same way.

### Fixed

- **`get_context` (MCP tool and `GET /api/context`), and the access-log purge in
  `gnosis-mcp cleanup`, raised `DataError` on Postgres.** `get_top_accessed` and
  `purge_access_log` bound `days` as an `int` into `($1 || ' days')::interval`;
  Postgres infers `$1` as `text` when it parses the statement, so asyncpg
  rejected the int at bind time. Both now bind `str(days)` — the same pattern
  `savings_report` and `client_usage` already use in the same file. SQLite
  interpolates the cutoff as a literal and never had the bug.

## [0.17.0] - 2026-09-10

Installing gnosis-mcp was never the hard part. Wiring it up was, and nobody
noticed how badly, because every failure in that half is silent: a client
pointed at a path that does not exist on your machine starts fine and registers
zero tools, and a perfectly wired client whose agent never reaches for it
returns nothing, logs nothing, and errors nowhere. This release makes the wiring
reproducible and gives you a way to see whether it worked.

### Added

- **`gnosis-mcp setup` — one command, ten clients, no paths to edit.** It
  resolves the server command for the machine it is running on instead of the
  one a README assumed, and writes each client's entry inside a marker-delimited
  managed block, so re-running after an upgrade rewrites one region in place
  rather than appending a duplicate. Text outside the markers is never read,
  reordered, or reformatted. Prints by default; nothing is written without
  `--write`.

  `gnosis-mcp` is rarely where a snippet expects it — `uv tool install` leaves a
  symlink in `~/.local/bin`, a venv install is reachable only through its own
  `bin`, and an MCP client spawns servers from a different working directory and
  a different `PATH` than your shell. `setup` writes the stable absolute path,
  and deliberately does not follow a console-script symlink into the package
  manager's private directory.

  Clients are a **registry**, not a chain of special cases: Claude Code, DeepSeek
  Harness, OpenAI Codex CLI, Gemini CLI, Cursor, VS Code, Windsurf, Cline, Zed,
  and a printed entry for anything else. Where a client ships its own `mcp add`
  command, that command is used and the config file is left to the vendor; if it
  exists but fails, `setup` reports the failure instead of quietly writing a
  second config the vendor's tooling would disagree with (`--no-cli` forces
  direct edits).

- **`setup` writes the rule that makes the agent use it.** An MCP server can
  return an `instructions` field and Claude Code surfaces it — `dsh-mcp-client`
  registers the tools and discards it. Mounting without that preamble produces
  tools the agent has no reason to prefer, which is the most common way a
  correct install goes unused. Where a client drops `instructions`, `setup`
  installs a short rule into that client's always-loaded instruction file
  (`$DSH_HOME/AGENTS.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`,
  `.cursor/rules/gnosis.mdc`). The rule is written only after the server entry
  exists: telling an agent to prefer tools its client has never heard of is
  worse than saying nothing.

- **`gnosis-mcp doctor` — is it installed, and is it actually being used?** A
  superset of `check`: database health, then which clients are wired and where,
  then the clients the access log says have really called this server. That last
  section is the only non-speculative answer to "will anyone use it", because it
  is evidence rather than intent. Exit `1` on an unhealthy database, an
  uninitialized schema, no wired client, or a composition the harness rejects.
  Wired-but-never-called is a warning — a machine that installed gnosis five
  minutes ago is in exactly that state — and `--strict` promotes it to an exit
  code for CI. On a DeepSeek Harness machine it also runs `dsh --dump-config`,
  which composes every layer and refuses to print a tree it cannot load: the only
  check that catches a row the loader rejects rather than one that merely looks
  wrong.

- **`DocBackend.client_usage()`** — per-client call counts and last-seen
  timestamps from `search_access_log`, on both backends. Returns an empty list
  rather than raising on a schema that predates the `client` column.

### Changed

- **The DeepSeek Harness row belongs in the profile patch layer, not an agent
  preset.** A preset is chosen per session and sessions on a shipped preset
  cannot be edited at all, so anything less than the profile layer means "gnosis
  is available in some sessions" — which is not a property an agent can rely on.
  The layer reloads live, so `setup --write` needs no restart.
- **`check` and `doctor` share one health probe**, so the shutdown path is
  identical on both and the failure messages cannot drift apart.

### Fixed

- **`setup` refuses to duplicate a hand-written wiring row.** Anyone who
  followed an earlier README has a `- id: mcp-gnosis` entry with no markers
  around it; appending a managed block would leave two rows carrying one id in a
  single patch array. It now stops and names the row to delete. (Found on the
  machine this was written on — the first real install hit it.)
- **`setup` no longer rewrites a config file it cannot parse**, and no longer
  half-writes one: every write goes through a sibling temp file plus
  `os.replace`, because a truncated client config takes every _other_ MCP server
  in that file down with it.
- **A `v*` tag push now creates the GitHub Release and the Codeberg mirror.**
  Both jobs declared `needs: [check, tag]`, and `tag` is skipped on a tag push —
  the tag already exists, that is what triggered the run. A skipped dependency
  skips its dependents, so the documented tag path published to PyPI and the MCP
  Registry and then created no release notes and no mirror, silently. Found by
  needing exactly that path: this release's own commit failed CI on a format
  check, and the retry had no `pyproject.toml` change left to trigger on.
- **`ruff format --check` is part of the release gate, not just the linter.**
  The first CI run of this release failed on it after `ruff check` and all 844
  tests passed locally — a fine way to learn that they are two different
  commands, a poor way to find out mid-release.

## [0.16.2] - 2026-09-10

A documentation release, plus the first contribution to land since 0.16.0.
Nothing in the package changed; what changed is whether you can find out how to
use it.

### Added

- **`llms-install.md` now carries an agent checklist.** Eight ordered steps, each
  with the command that verifies it and what to do when it fails, for the case
  where you ask an AI agent to set gnosis-mcp up on your behalf. Step 3 probes
  SQLite for FTS5 _before_ anything is ingested, because a Python built without
  FTS5 fails in the worst possible way: every later step appears to succeed while
  search quietly returns nothing.
- **Platform guidance** for Linux/macOS, native Windows (including the full
  `gnosis-mcp.exe` path an MCP client needs), WSL2, and a remote/VM deployment
  over streamable HTTP, with a worked Windows server entry.

### Changed

- **The README is 284 lines instead of 706.** It had grown into a second copy of
  the documentation — the full configuration reference, the tools reference, the
  REST API, deployment, and 84 lines of per-editor JSON. Those are pointers now,
  and a `## Documentation` index makes the whole `docs/` tree reachable from the
  front page; nine of the thirteen documents were unreachable before.
- **Doc links in the README are absolute.** It doubles as the PyPI package page,
  where relative links do not resolve — `](docs/cli.md)` became
  `pypi.org/project/gnosis-mcp/docs/cli.md`, a 404. There were 22 of them.
- `skills/setup/SKILL.md` no longer restates the install procedure; it points at
  `llms-install.md`, the one canonical copy (−128 lines). That duplication is how
  the wrong config path for Claude Code spread across several files at once, and
  how "9 tools" outlived the behaviour by three releases.

### Fixed

- **OpenAI-compatible embedding requests identify the client** — remote
  gateways may reject requests with no `User-Agent`; OpenAI-compatible
  embedding requests now send `gnosis-mcp/<version>`. This preserves the
  existing request body and authentication behavior while improving
  compatibility with hosted OpenAI-compatible gateways, including Nous
  Portal-style endpoints.
- **Six environment variables the code reads were documented nowhere**:
  `GNOSIS_MCP_COLLAPSE_BY_DOC`, `GNOSIS_MCP_FTS5_TITLE_WEIGHT`,
  `GNOSIS_MCP_FTS5_CONTENT_WEIGHT`, `GNOSIS_MCP_MMR_LAMBDA`,
  `GNOSIS_MCP_RERANK_MODEL` and `GNOSIS_MCP_RERANK_POOL`. Comparing every variable
  the code reads against `docs/config.md` now comes back empty.
- `GNOSIS_MCP_SEARCH_FUNCTION` documented a signature the server never calls. It
  now shows the real call (`p_query_text`, `p_embedding`, `p_categories`,
  `p_limit`) and the columns a custom function must return.
- Multi-table mode's two unstated rules: the tables must share a schema, and
  writes target the first one.
- `gnosis-mcp savings` had no entry in the CLI reference, and `POST /v1/embed` was
  missing from the REST reference.
- Tool counts in `docs/overview.md` and `docs/tools.md` still said nine tools
  without the read/write gating, and the README claimed 632 tests where the suite
  collects 782. `docs/troubleshooting.md` gained the two missing first-run
  failures: FTS5 unavailable, and `check` exiting 1 on a brand-new database.

### Security

## [0.16.1] - 2026-09-10

### Added

- `--include-generated` on `prune` and `ingest`, the opt-in for pruning generated
  documents (currently git history). See Fixed.

### Changed

- Two `chunk_index`-level behaviours from 0.16.0 need a _forced_ re-ingest to
  reach an existing corpus; the 0.16.0 entry now spells out `--force` and the
  `embed` pass that must follow it.

### Fixed

- **`prune` deleted generated documents.** `prune <root>` deletes every document
  whose `file_path` is not a file under that root, and only absolute paths and
  URLs were excluded from consideration — so a _relative_ path that no file can
  back, which is precisely what a generating ingester writes, looked stale.
  Pruning a knowledge root reported "Would prune 431 stale document(s)": the
  entire git-history corpus. Since the README recommends
  `gnosis-mcp ingest ./docs --prune` after re-organizing a folder, and `--prune`
  runs this same code, the documented cleanup path destroyed them.
  Generated documents are now out of scope unless `--include-generated` is
  passed. Nothing else about pruning changed: files genuinely deleted from the
  root are still removed, and that is covered by a test so the guard cannot
  quietly disable the feature.
- The "no stale documents" message claimed everything in the database existed on
  disk. It reports how many documents were in scope for that root instead, which
  is the only claim the check can support.

### Security

## [0.16.0] - 2026-09-10

This release comes out of a full feature retest of v0.15.0 — every CLI
subcommand, MCP tool, resource and REST route exercised against isolated
databases — plus the first contribution from outside the project (see Fixed).
Several defects were only reachable because the retest used a corpus and a
configuration the author had never tried.

### Added

- **`rerank_score` reaches the client.** Reranking reordered results but the
  score it computed never left the server, so a reranked result set shipped
  retrieval scores that contradicted the order the caller was reading. `category`
  is passed through with it, and only when present.
- `serve` probes the configured reranker at startup — a HEAD request, instant
  when the model is cached, never fatal — so an unfetchable model is reported
  rather than silently degrading every search.
- Per-invocation guidance from the CLI: eight subcommands now answer a
  never-initialized database with one line naming `gnosis-mcp init-db` and
  `gnosis-mcp ingest <path>` instead of a raw driver traceback.

### Changed

- **Re-ingest to pick up preamble content.** `chunk_by_headings` started its
  first chunk at the first H2, so the H1 and the introductory prose never became
  chunks: text in that region was unsearchable, and a document's title came out
  as its first H2. A document whose unique phrase lived in the intro could not be
  found by `search_docs` at all. Applying this to an existing corpus needs
  `gnosis-mcp ingest <path> --force`: ingest skips files whose content hash is
  unchanged, and the files have not changed, so a plain re-ingest reports
  everything "unchanged" and re-chunks nothing. Run `gnosis-mcp embed` afterwards
  to restore vectors for the re-chunked documents, which re-chunking deletes.
- **`get_related` is monotonic in depth.** `depth=2` returned _fewer_ rows than
  `depth=1` (5 → 3 → 3) because the traversal deduplicated results on the target
  path, discarding the first hop's parallel edges — the same neighbour reached in
  the opposite direction, or through a second relation type. Deeper traversal is
  now a superset of shallower.
- **The default reranker model is one that exists.** `config.py` defaulted to
  `onnx-community/ms-marco-MiniLM-L6-v2-ONNX`, which returns HTTP 401, while
  `rerank.py`'s own default was already the correct
  `cross-encoder/ms-marco-MiniLM-L6-v2`. Both now agree, and an unfetchable model
  fails with the URL, the status and both remedies instead of a silent fallback.
- `export -f csv` reports the real chunk count. It previously counted blank lines
  in the joined content, reporting 6 chunks for a 2-chunk document.
- `crawl` honours `XDG_DATA_HOME` for its cache. The path was hardcoded, so an
  isolated run — a test, a container, CI — wrote into the user's live cache.
- Agent definitions under `agents/` no longer claim write access they should not
  have, and no longer document CLI flags that do not exist.

### Fixed

- **`serve --rest` with `--transport streamable-http` no longer breaks `/mcp`.**
  Every MCP request returned HTTP 500 while the REST routes worked: the combined
  app mounted the MCP app but ran only the REST lifespan, and Starlette never
  enters a mounted sub-app's lifespan — which is where FastMCP starts the
  streamable-HTTP session task group. Both surfaces now serve one port as
  documented.
- **`diff` and `ingest` agree about PDFs.** Ingest hashed raw bytes while `diff`
  hashed decoded text, so every PDF was reported as modified forever.
- **A total embedding failure is no longer exit 0** (contributed by
  @kikeamzar in #11). `embed` and `ingest --embed` reported success while
  embedding nothing, which any wrapping script or CI read as a healthy run.
- `fix-link-types` crashed with an unhandled `IntegrityError` on the upgraded
  database shape it exists to migrate.
- Documentation corrected where it disagreed with the code: `ingest-git` and
  `crawl` flags that do not exist, `eval` described as evaluating your corpus
  when it uses a fixed fixture, `GNOSIS_MCP_PUBLIC_PATHS` documented but never
  implemented, and four wrong REST response samples.

### Security

## [0.15.0] - 2026-09-10

This release is the first that treats a non-Claude MCP client as a first-class
caller. Every fix below was found by wiring gnosis-mcp into a second client and
watching what that client actually saw over the wire.

### Added

- **The MCP `instructions` field.** `initialize` now carries the standard
  `instructions` guidance describing when to reach for each tool. Until now the
  server's only prose description of itself lived in a client-specific
  `serverInstructions` key in `.mcp.json`, which most MCP clients ignore
  entirely — a tools-only client got terse docstrings and nothing else.
- **Per-client access-log attribution.** `search_access_log` records the calling
  client's `clientInfo` (name and version) from the MCP handshake, so a database
  shared by two clients no longer conflates their traffic irrecoverably — the
  column can be queried per client. (Surfacing that in the `savings` and `stats`
  output is a follow-up; those still aggregate by tool today.)
  Existing SQLite databases migrate themselves on the
  next start. **PostgreSQL keeps working unchanged but does not self-migrate** —
  that backend has no post-release column mechanism at all, so an existing PG
  schema needs `ALTER TABLE <schema>.search_access_log ADD COLUMN client text;`
  once. Until then the column is feature-detected and simply omitted from the
  insert, exactly as the token columns already are.
- `serve --search-limit-max` and `serve --content-preview-chars` mirror the
  `GNOSIS_MCP_SEARCH_LIMIT_MAX` / `GNOSIS_MCP_CONTENT_PREVIEW_CHARS` environment
  variables, so verbosity is adjustable per invocation.

### Changed

- **Write tools are no longer advertised when writes are disabled.**
  `upsert_doc`, `delete_doc` and `update_metadata` are withdrawn from
  `tools/list` unless `GNOSIS_MCP_WRITABLE=true`, so a read-only client sees six
  useful tools instead of nine, three of which could only ever return an error.
  The in-call `cfg.writable` gate is unchanged, so no call becomes possible that
  was not possible before.
- **Tool failures now report MCP `isError: true`.** They previously returned a
  `{"error": ...}` body inside a _successful_ result, which meant a failed call
  was indistinguishable from data and no client could retry, render, or gate on
  it uniformly. The JSON payload text is unchanged.

### Fixed

- **`serverInfo.version` reported the `mcp` SDK's version.** Clients were told
  `1.27.0` — the SDK pin — instead of gnosis-mcp's own version, because FastMCP
  never forwards a version to the low-level server, which then falls back to its
  own. Anything version-gating on the handshake was reading a lie.
- **A cold start no longer fails every call.** `serve` against a database that had
  never been initialised advertised every tool and then failed each call with
  `no such table documentation_chunks_fts`. Only `init-db`, `ingest` and `eval`
  ever created the schema, so the documented install order (ingest before serve)
  hid a first run that was broken for anyone who wired the server up first —
  which is exactly what a new MCP client does.
- **`gnosis-mcp check` always exited 0**, including against an uninitialized or
  unreachable database, so it could not gate a setup script, installer, or CI.
  It now exits 1 when the schema is incomplete and names the missing pieces.
- The `no such table` hint pointed at `check`, which only diagnoses; it now names
  `init-db` and `ingest`.

### Security

## [0.14.1] - 2026-08-20

For PyPI users this is the first release since 0.13.3 that actually shipped:
the v0.14.0 publish run failed its version-parity gate (see Fixed below), so
0.14.1 is the release that delivers the v0.14.0 features (`POST /v1/embed`)
to PyPI, plus the security hardening and a dependency refresh.

### Changed

- **Dependency refresh** — `uv.lock` upgraded across the board (starlette
  1.0 → 1.6, uvicorn 0.44 → 0.52, sse-starlette 3.3 → 3.4, tokenizers
  0.22 → 0.23, trafilatura 2.0 → 2.2, among others). All 687 tests pass on
  the new set.
- Dev tooling: pinned `ruff>=0.14,<0.16`. ruff 0.16 introduces ~90 new
  findings (largely `BLE001` blind-except hits in deliberate log-and-continue
  paths); adopting it deserves a dedicated pass, not a drive-by inside a
  dependency bump.

### Fixed

- **Version parity completed for the v0.14.0 bump** — the v0.14.0 release
  commit updated only four of the version-bearing files; `.claude-plugin/plugin.json`,
  `pkg/arch/PKGBUILD`, `pkg/arch/.SRCINFO`, and `docs/rest-api.md` stayed at
  0.13.3, so `check-versions.sh` failed the publish `check` job in 8 seconds
  and v0.14.0 never reached PyPI, never got a tag, and never produced a GitHub
  Release (a quieter cousin of the v0.11.4–v0.13.2 pipeline skip). This
  release realigns every file via `scripts/bump-version.sh`.
- `ruff format` drift in `src/gnosis_mcp/rest.py` (introduced with the
  `/v1/embed` work) that failed CI on main and would have failed the publish
  `test` job even past the parity gate.

### Security

- **Warn on unauthenticated public REST bind** (previously committed as
  `ea154de` but never released): when `--rest` is enabled on a non-loopback
  host with no `GNOSIS_MCP_API_KEY` — the Docker default binds `0.0.0.0` —
  the server now logs a loud SECURITY warning, since the read API and
  `/v1/embed` would otherwise be open to anyone who can reach the port.
  Warning rather than fail-closed, to avoid breaking running deployments.
- **sdist scoped** (same commit): `[tool.hatch.build.targets.sdist]` now
  excludes `docs/`, `scripts/`, `tests/`, `.github/`, `.claude/`, and
  `*.db`, so internal files with absolute machine paths no longer ship in
  the public PyPI source tarball.

## [0.14.0] - 2026-05-26

### Added

- **`POST /v1/embed` — first-class embeddings endpoint.** OpenAI-compatible
  shape (`{texts, model?}` → `{model, dim, vectors, usage}`), so any client that
  already speaks OpenAI's embeddings API can point at gnosis-mcp and get a
  drop-in self-hosted alternative. Embeddings were already used internally for
  the `/api/search` auto-embed path, but external services couldn't call them
  directly; this exposes that work as a stable public endpoint.

  Per-request `model` override is supported, locked to the configured provider
  (`GNOSIS_MCP_EMBED_PROVIDER`). Reuses the existing `ApiKeyMiddleware` Bearer
  auth, so deploying gnosis-mcp as a shared team embeddings service works the
  same way as locking down the existing REST API.

  Limits: max 256 texts per request, max 50 KB per text. Returns 400 on shape
  errors, 503 when the `[embeddings]` extra is missing or the provider raises.

### Changed

- CORS preflight now advertises `GET, POST, OPTIONS` (was `GET, OPTIONS`) so
  browser clients can call `POST /v1/embed` without a CORS rejection.

## [0.13.3] - 2026-04-19

### Fixed

- **Publish pipeline unblock** — every release since v0.11.3 had its `test` job fail on `ruff format --check` (I was running `ruff check` locally but not `ruff format`). Because `test` gates every downstream job in `publish.yml`, PyPI, MCP Registry, tag creation, GitHub Release, Codeberg mirror, and the Arch-sums auto-PR were all skipped for ten consecutive releases. Net effect: the main branch had code up to v0.13.2 while PyPI was stuck at 0.11.3 and gnosismcp.com rendered v0.11.2. Applied `ruff format` to the 9 files it flagged (no logic change, whitespace + line-break normalisation only) and cut this dead-simple patch so the pipeline gets another push to react to. No functional code change versus v0.13.2.

### Security

## [0.13.2] - 2026-04-19

### Changed

- **README reshape** — Performance section now sits right after Features (was near the bottom of a 700-line file) so the numbers that matter to a new reader hit within the first three screenfuls. Added a `## Performance → Tokens saved` paragraph with a live `gnosis-mcp savings` sample output — evidence for the token-savings claim the landing page makes, now matching in the primary doc.
- **Configuration table compressed to 5 rows** — the full ~40-variable list moved behind a link to `docs/config.md` and the site equivalent at `gnosismcp.com/doc/docs/config`. Casual readers see the decisions they actually need to make on day one; power users follow one link for the rest.
- **Transport section cut from 32 lines to 13** — stdio vs HTTP tradeoff stays explicit, the full rationale + systemd/Docker notes moved to `gnosismcp.com/doc/docs/deployment`.
- **REST API section cut to the endpoint table** — env vars and curl examples moved to `docs/rest-api.md` / `gnosismcp.com/doc/docs/rest-api`. The endpoint table stays because it's the thing someone scanning for "can I hit this from a web app" needs at a glance.

### Fixed

- No code changes; README-only. PyPI re-renders on any README change so the patch bump is required per project policy.

### Security

## [0.13.1] - 2026-04-19

### Fixed

- **`gnosis-mcp savings` no longer raises `OperationalError: no such column: tokens_returned`** on databases created before v0.12 (`sqlite_backend.py`). The v0.12.0 schema migration was tied to `init_schema()` — called during `gnosis-mcp init-db`, not during normal `startup()` — so any existing user who skipped `init-db` after upgrading hit a hard crash when running the `savings` CLI. Migration now runs from `startup()` via `_ensure_post_v0_12_columns()` (idempotent ALTER TABLE per missing column), and `savings_report()` itself feature-detects the columns and returns all-zeros rather than raising when an unusual schema is encountered. Regression test builds a v0.11.x-shaped table directly, brings up the backend, and asserts the report method doesn't crash.
- **`tests/bench/sweep_new_knobs.py`** — dev-time 4-config sweep script added for anyone investigating the effect of `COLLAPSE_BY_DOC` × `MMR_LAMBDA` on their own corpus. Runs the same 30 goldens through the full server-side pipeline (backend.search → MMR → collapse-by-doc → truncate) so post-processor effects actually show up. First published numbers on the laptop dev-docs corpus: collapse-by-doc +2.2 nDCG points, MMR λ=0.6 −24 nDCG points + 48× latency (because candidate content re-embedding). MMR is opt-in and the knob works; the bench just doesn't test the use case MMR is designed for (diverse multi-intent queries rather than single-target lookups).

### Security

## [0.13.0] - 2026-04-19

### Added

- **`GNOSIS_MCP_MMR_LAMBDA`** — opt-in Maximal Marginal Relevance (Carbonell & Goldstein 1998) re-ranking for `search_docs`. Default `1.0` = pure relevance (current behaviour, exact identity). Any value in `(0.0, 1.0)` enables greedy diversity-aware reordering: at each step the candidate maximising `λ · cos(q, d) − (1 − λ) · max_{d' ∈ S} cos(d, d')` wins, where `S` is the already-picked set. `λ=0.6` is the community default for dev-docs where moderate diversity helps without abandoning relevance. Runs on the top-K candidates after rerank (if enabled) and before `collapse_by_doc`. Embeds candidate content on-the-fly via the existing local embedder — no new dependency, no backend API change. Fail-soft: any exception in the embedding path logs a warning and returns the original order, so misconfiguration degrades instead of breaking `search_docs`.
- `fetch_limit` auto-bumps to `limit × 5` when MMR is active, mirroring the collapse-by-doc headroom pattern — MMR only diversifies what it's given, so a bigger candidate pool produces a better top-K. No overlap cost when both features are on; the fetch bumps compose via `max`.

### Security

## [0.12.0] - 2026-04-19

### Added

- **`gnosis-mcp savings` CLI** and `savings_report()` backend method. Aggregates the new `tokens_returned` + `tokens_baseline` columns on `search_access_log` into a per-tool breakdown of estimated tokens saved. Token count uses a 4-chars-per-token heuristic — close enough to GPT/Claude tokenisers for relative trend tracking without needing a tiktoken dependency. Per-call savings accumulate over time; `--days N` windows the aggregation, `--json` emits the raw shape for piping into observability dashboards. When `access_log` is disabled (`GNOSIS_MCP_ACCESS_LOG=false`) the CLI reports zero with a hint explaining why.
- **`search_access_log.tokens_returned` + `tokens_baseline` columns** (`sqlite_schema.py`). Populated by `search_docs` and `get_doc` on every call. `tokens_returned` is what the caller received; `tokens_baseline` is what the caller would have spent reading the full document naively. `ALTER TABLE ADD COLUMN` migration in `SqliteBackend.init_schema()` retrofits existing databases idempotently; `PostgresBackend.log_access()` feature-detects the columns via `information_schema` and falls back to the old three-column INSERT so pre-0.12 PG schemas keep writing access rows while the user rolls out the new DDL.
- **README tagline + before/after contrast updated** to surface the concrete numbers (5–10× token savings, 92 % Hit@5) up top. Quick Start section now shows both `pip install` and `uv tool install` — the two install paths most users actually take in 2026.
- **Landing-page (gnosismcp.com) metrics paragraph** gained one sentence quantifying the token-cost delta (~300–800 returned vs 3,000–15,000 for a full Read, ~5–10× savings). Structural layout untouched.

### Security

## [0.11.7] - 2026-04-19

### Added

- **`GNOSIS_MCP_COLLAPSE_BY_DOC`** (`server.py`). Opt-in top-K deduplication — keeps at most one chunk per distinct `file_path`, preserving incoming rank order (so the highest-scoring chunk per doc wins). Rescues the failure mode where a long document with many similar chunks (e.g. a single llms-full.txt that chunks into 1000+ fragments) drowns out the rest of the results. Fetch limit scales to `limit × 5` when enabled so there's enough headroom after collapse to still return `limit` distinct docs. Default off to preserve existing result shapes; `GNOSIS_MCP_COLLAPSE_BY_DOC=true` turns it on.
- **`GNOSIS_MCP_FTS5_TITLE_WEIGHT` + `GNOSIS_MCP_FTS5_CONTENT_WEIGHT`** (`sqlite_backend.py`). SQLite FTS5 column weights previously hardcoded as `bm25(..., 10.0, 1.0)` are now configurable via env vars. Defaults preserve the 10:1 title-vs-content ratio so existing rankings don't shift; downstream users with unusual docs (massive titles, wiki-style cross-references, etc.) can rebalance without forking.

### Changed

- **Dead `__all__` entries dropped** (`schema.py`, `parsers/git_history.py`). `SCHEMA_SQL`, `FileHistory`, and `GitIngestResult` were re-exported via `__all__` but never imported by any caller in the repo. `SCHEMA_SQL` is an implementation detail of `get_init_sql()`; the two dataclasses are internal data carriers. Public-API surface stays intact (`GitCommit` and `GitIngestConfig` remain exported).

### Fixed

- **BFS crawl discovery silently swallowed fetch errors** (`crawl.py:477`). The `except Exception: continue` block ate transient HTTP errors during link discovery, leaving users to wonder why their `--max-urls 200` crawl only pulled 30 pages. Now logs at debug level so `LOG_LEVEL=DEBUG` reveals the dropped URLs without adding noise at the default level.

### Security

## [0.11.6] - 2026-04-19

### Added

### Changed

### Fixed

- **Local embed provider no longer inherits the OpenAI default model** (`config.py`). `GNOSIS_MCP_EMBED_PROVIDER=local` with no `EMBED_MODEL` used to leave `embed_model="text-embedding-3-small"` (the OpenAI default), then pass that into `LocalEmbedder`, which tried to `GET https://huggingface.co/text-embedding-3-small/…` and 401'd. This was the exact failure every first-time user hit after wiring gnosis-mcp into Claude Code. `__post_init__` now swaps in `MongoDB/mdbr-leaf-ir` when provider is local and the user didn't pick a model. Explicit `EMBED_MODEL` values are preserved; non-local providers keep their own defaults.
- **Auto-embed failure in `search_docs` + `/api/search` no longer crashes the request** (`server.py` + `rest.py`). A HuggingFace 401 / network blip / wrong model id used to propagate out of the tool as an unhandled exception, so the whole search failed instead of returning FTS5 results. Both callsites now catch `Exception`, log a warning, and fall back to keyword-only — hybrid degrades instead of breaking.
- **MCP semantic-search env documentation** (`llms-install.md`). The "Optional: Add Semantic Search" section used to cover CLI usage (`gnosis-mcp search --embed`) but didn't mention that MCP clients calling `search_docs` need `GNOSIS_MCP_EMBED_PROVIDER=local` in the server's env block. Added the missing JSON snippet and a note about `GNOSIS_MCP_EMBED_MODEL` override + graceful-fallback behaviour.

### Security

## [0.11.5] - 2026-04-19

### Added

### Changed

### Fixed

- **Binary files with a text extension no longer ingest as garbled markdown** (`ingest.py`). A PNG mistakenly saved as `image.txt` used to pass the UTF-8-replace pathway, storing `# Image\n\n�PNG\n^Z…` as searchable content and polluting both FTS5 and dense indexes with junk tokens. New `_looks_binary()` helper samples the first 2KB and skips anything containing NUL bytes — the strongest unambiguous not-text signal.
- **Empty Jupyter notebooks no longer index their raw JSON wrapper** (`ingest.py`). `_convert_ipynb` fell back to `return text` when `cells == []`, meaning `{"cells": [], "metadata": {}, "nbformat": 4, ...}` got stored as the document's content. Now returns `""` so the new post-convert size guard skips it cleanly.
- **Post-convert size guard applied to every format, not just PDF** (`ingest.py`). The pre-convert 50-char threshold caught tiny raw files but let converters with vacuous output (empty ipynb, CSVs with only a header row) through to write a single empty chunk. Added the same `if len(md_text.strip()) < 50: skip` clause for plain-text / JSON / TOML / CSV / ipynb, mirroring PDF's existing path.
- **`tags: [alpha, beta]` frontmatter now parses as `["alpha", "beta"]` instead of `["[alpha", "beta]"]`** (`ingest.py`). `parse_frontmatter` treats every value as a string and the downstream code did a naive `split(",")`, so YAML inline-list syntax leaked the literal `[` and `]` characters into the stored tags. New `_parse_tags_value()` strips enclosing brackets before splitting and also strips surrounding quotes on each entry; tests cover inline-list, comma-separated, quoted, and blank-dropping cases.

### Security

## [0.11.4] - 2026-04-19

### Added

### Changed

### Fixed

- **`documentation_chunks_vec` vectors no longer leak on re-ingest** (`sqlite_schema.py` + `sqlite_backend.py`). The FTS shadow table had INSERT/DELETE/UPDATE triggers keeping it in lockstep; the vec0 virtual table had none. Every `upsert_doc` path (plus `delete_doc` and the git-history re-ingest) does a `DELETE FROM documentation_chunks WHERE file_path = ?` followed by fresh INSERTs — old vec0 rows were left behind as orphans pointing to gone chunk IDs. Over months of dogfooding, a dev laptop DB had 4528 vectors vs 4267 chunks (261 orphan leak). New `chunks_ad_vec` trigger mirrors the FTS pattern: `AFTER DELETE ON documentation_chunks → DELETE FROM documentation_chunks_vec WHERE chunk_id = OLD.id`. `get_vec0_schema()` now returns a list; regression test covers the full upsert-delete-upsert cycle and asserts post-condition count parity. Existing DBs carry their historical orphans until they're re-initialized — there's no automatic migration because the count bug is cosmetic (orphan rows never get returned by KNN since their chunk_ids don't join back to anything in `documentation_chunks`).
- **`gnosis-mcp diff <path>` no longer reports crawled URLs and git-history pseudo-paths as "deleted from disk"** (`ingest.py`). `diff_path` scanned the filesystem under `<path>` and pulled _all_ stored file paths from the DB, then marked anything not found on disk as deleted — but crawled URLs (`https://…`) and git-history docs (`git-history/…`) live only in the DB by design. A laptop with ~700 crawled URLs ran `diff README.md` and saw every URL listed as `[-] deleted`. `prune` had already addressed this via `--include-crawled`; `diff` now filters the same pseudo-paths unconditionally. Regression test seeds a URL and a git-history row alongside a real file and asserts the deleted bucket stays empty.
- **`/health` distinguishes docs from chunks** (`rest.py` + `sqlite_backend.py` + `pg_backend.py`). Previously the endpoint labeled the post-chunking row count under the `"docs"` key — on a 700-doc corpus with typical chunking this read as ~4000 docs, throwing off load balancers' expected-range checks and confusing anyone reconciling `/health` against `gnosis-mcp stats`. Both backends' `check_health()` now also return `docs_count` (distinct `file_path` count); the REST response carries both `"docs"` (distinct) and `"chunks"` (rows).

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
