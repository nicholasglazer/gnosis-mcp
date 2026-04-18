# v0.9.0 Design: Git History Ingestion

## Problem

AI agents working on a codebase can read current code but have no access to *why* things were built a certain way. Commit messages, PR descriptions, and change history contain critical context: past decisions, reverted approaches, migration rationale. Without this, agents repeat mistakes the team already learned from.

> "My AI keeps trying to refactor code back to the 'obvious' pattern. It doesn't know we tried that, it caused a race condition, and we reverted it 3 months ago."

## Solution

A new CLI command `gnosis-mcp ingest-git <repo-path>` that converts git history into searchable markdown documents flowing through the existing ingest pipeline. No new search engine, no new schema, no new tools.

## How It Works

### Input

Git repository (local path). Uses `git log` via subprocess — zero new dependencies.

### Output

One markdown document per file that has meaningful commit history. Each commit becomes an H2 section.

```markdown
---
title: "History: src/lib/billing.ts"
category: git-history
---
# src/lib/billing.ts — Change History

## 2026-02-15: Switch to charge-before-service pattern (a3f8b21)
Author: ng

Changed billing flow to charge BEFORE service delivery.
Previous approach (charge-after) caused revenue leakage when
GPU workers failed mid-generation.

Files changed: src/lib/billing.ts, src/lib/stripe.ts, tests/billing.test.ts

## 2026-01-28: Add Stripe webhook idempotency (7c2e9f4)
Author: ng

Added idempotency_key to prevent duplicate charges from
webhook retries.
```

### Pipeline

```
git log --format  →  group by file  →  render markdown  →  chunk_by_headings()
                                                           → backend.ingest_file()
```

Each file's history document flows through the existing chunking, hashing, embedding, and storage pipeline. The `file_path` is prefixed: `git-history/src/lib/billing.ts` to avoid collision with actual file docs.

## CLI

```bash
# Basic: ingest recent history for the current repo
gnosis-mcp ingest-git .

# With options
gnosis-mcp ingest-git /path/to/repo \
    --since 6m \                      # only commits from last 6 months
    --max-commits 10 \                # max commits per file (most recent)
    --include "src/**" \              # only these paths
    --exclude "*.lock,package.json" \ # skip these
    --embed \                         # embed for semantic search
    --dry-run                         # preview without ingesting

# Re-ingest (incremental — skips files with unchanged history)
gnosis-mcp ingest-git . --since 6m
```

## How Agents Use It

No new tools needed. The agent calls `search_docs` like always:

```
search_docs("why was billing changed")
→ git-history doc about charge-before-service decision

search_docs("webhook idempotency")
→ git-history doc about the Stripe fix

search_docs("what changed in auth", category="git-history")
→ scoped to only history documents
```

The `get_related` tool also works if the original source file has docs:
```
get_related("src/lib/billing.ts")
→ includes "git-history/src/lib/billing.ts" as a related document
```

## Module: `src/gnosis_mcp/parsers/git_history.py`

### Data types

```python
@dataclass
class GitCommit:
    hash: str
    author: str
    date: str          # ISO format
    subject: str       # first line of commit message
    body: str          # rest of commit message
    files: list[str]   # files changed in this commit

@dataclass
class FileHistory:
    file_path: str
    commits: list[GitCommit]

@dataclass(frozen=True)
class GitIngestConfig:
    since: str | None = None          # "6m", "2025-01-01", etc.
    max_commits: int = 10             # per file
    include: str | None = None        # glob pattern for file paths
    exclude: str | None = None        # glob pattern to skip
    embed: bool = False
    dry_run: bool = False
    merge_commits: bool = False       # include merge commits (default: skip)
```

### Functions

Pure (testable without git):
- `parse_git_log(log_output: str) -> list[GitCommit]` — parse `git log` formatted output
- `group_by_file(commits: list[GitCommit]) -> dict[str, list[GitCommit]]` — group commits by file path
- `render_history_markdown(file_path: str, commits: list[GitCommit]) -> str` — render as markdown document
- `should_include(path: str, include: str | None, exclude: str | None) -> bool` — fnmatch filter

Async (needs subprocess):
- `run_git_log(repo_path: str, config: GitIngestConfig) -> str` — execute git log with format string
- `ingest_git(gnosis_config, repo_path: str, config: GitIngestConfig) -> list[IngestResult]` — orchestrator

### Git Log Format

```bash
git log --format="COMMIT_START%nHASH:%H%nAUTHOR:%an%nDATE:%aI%nSUBJECT:%s%nBODY_START%n%b%nBODY_END" \
    --name-only \
    --no-merges \
    --since="6 months ago" \
    -- '*.py' '*.ts' '*.svelte'
```

Custom format with delimiters for reliable parsing. `--name-only` gives changed files per commit. `--no-merges` skips noise by default.

### Content Hashing

Use the latest commit hash per file as the content hash. On re-run, if the latest commit for a file hasn't changed, skip it. This makes incremental re-ingestion fast.

## Auto-Linking

For each file in the git history, automatically create a `relates_to` link to the actual file path (if it exists in the docs database). This makes `get_related("src/lib/billing.ts")` return both documentation and history.

## What's NOT in v0.9.0

- PR descriptions (requires GitHub/GitLab API — deferred to v0.9.1)
- Diff content (too noisy for search — just commit messages)
- Branch comparison ("what changed between main and feature-x")
- Blame per line (too granular, poor search quality)
- Schema ingestion, dependency graphs, test specs (v0.10+)

## Testing

- Pure function tests: parse_git_log, group_by_file, render_history_markdown, should_include (~30 tests)
- Integration tests with a temp git repo (create commits programmatically) (~10 tests)
- CLI test: dry-run output format
- Incremental test: re-run skips unchanged files

## Files to Modify

| File | Change |
|------|--------|
| `src/gnosis_mcp/parsers/__init__.py` | NEW — package init |
| `src/gnosis_mcp/parsers/git_history.py` | NEW — ~250 lines |
| `src/gnosis_mcp/cli.py` | Add `ingest-git` subcommand (~40 lines) |
| `tests/test_git_history.py` | NEW — ~40 tests |
| `pyproject.toml` | Bump to 0.9.0 |
| `CHANGELOG.md` | Add 0.9.0 entry |
