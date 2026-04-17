"""Git history parser: convert commit history into searchable markdown documents.

Uses ``git log`` via subprocess — zero new dependencies.
Produces one markdown document per file with meaningful commit history.
Each commit becomes an H2 section, flowing through the existing ingest pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gnosis_mcp.config import GnosisMcpConfig

__all__ = [
    "GitCommit",
    "FileHistory",
    "GitIngestConfig",
    "GitIngestResult",
    "parse_git_log",
    "group_by_file",
    "render_history_markdown",
    "should_include",
    "ingest_git",
]

log = logging.getLogger("gnosis_mcp")

# Delimiter used in git log --format to reliably parse commits
_COMMIT_SEP = "---GNOSIS_COMMIT---"
_BODY_START = "---GNOSIS_BODY_START---"
_BODY_END = "---GNOSIS_BODY_END---"
_FILES_START = "---GNOSIS_FILES---"


@dataclass
class GitCommit:
    """A single parsed git commit."""

    hash: str
    author: str
    author_email: str
    date: str  # ISO 8601
    subject: str
    body: str
    files: list[str] = field(default_factory=list)


@dataclass
class FileHistory:
    """Commit history for a single file."""

    file_path: str
    commits: list[GitCommit]


@dataclass(frozen=True)
class GitIngestConfig:
    """Configuration for git history ingestion."""

    since: str | None = None  # e.g. "6m", "2025-01-01"
    until: str | None = None  # e.g. "2026-02-20"
    author: str | None = None  # filter by author name/email
    max_commits: int = 10  # per file, most recent
    include: str | None = None  # glob pattern for file paths
    exclude: str | None = None  # glob pattern to skip
    embed: bool = False
    dry_run: bool = False
    merge_commits: bool = False  # include merge commits
    force: bool = False  # re-ingest even if content hash unchanged


@dataclass
class GitIngestResult:
    """Result of ingesting git history for one file."""

    path: str
    commits: int
    chunks: int
    action: str  # "ingested", "unchanged", "skipped", "dry-run", "error"
    detail: str = ""


# ---------------------------------------------------------------------------
# Pure functions (testable without git or database)
# ---------------------------------------------------------------------------


def parse_git_log(log_output: str) -> list[GitCommit]:
    """Parse custom-formatted git log output into GitCommit objects.

    Expects the format produced by ``_git_log_format()``.
    """
    if not log_output.strip():
        return []

    commits: list[GitCommit] = []
    blocks = log_output.split(_COMMIT_SEP)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        commit_hash = ""
        author = ""
        author_email = ""
        date = ""
        subject = ""
        body = ""
        files: list[str] = []

        lines = block.split("\n")
        in_body = False
        in_files = False
        body_lines: list[str] = []

        for line in lines:
            if line.startswith("HASH:"):
                commit_hash = line[5:].strip()
            elif line.startswith("AUTHOR:"):
                author = line[7:].strip()
            elif line.startswith("EMAIL:"):
                author_email = line[6:].strip()
            elif line.startswith("DATE:"):
                date = line[5:].strip()
            elif line.startswith("SUBJECT:"):
                subject = line[8:].strip()
            elif line == _BODY_START:
                in_body = True
                in_files = False
            elif line == _BODY_END:
                in_body = False
            elif line == _FILES_START:
                in_files = True
                in_body = False
            elif in_body:
                body_lines.append(line)
            elif in_files and line.strip():
                files.append(line.strip())

        body = "\n".join(body_lines).strip()

        if commit_hash:
            commits.append(
                GitCommit(
                    hash=commit_hash,
                    author=author,
                    author_email=author_email,
                    date=date,
                    subject=subject,
                    body=body,
                    files=files,
                )
            )

    return commits


def group_by_file(commits: list[GitCommit]) -> dict[str, list[GitCommit]]:
    """Group commits by file path, preserving chronological order (newest first)."""
    groups: dict[str, list[GitCommit]] = {}
    for commit in commits:
        for f in commit.files:
            groups.setdefault(f, []).append(commit)
    return groups


def should_include(path: str, include: str | None, exclude: str | None) -> bool:
    """Check if a file path passes include/exclude filters."""
    if exclude:
        for pattern in exclude.split(","):
            pattern = pattern.strip()
            if pattern and fnmatch(path, pattern):
                return False
    if include:
        for pattern in include.split(","):
            pattern = pattern.strip()
            if pattern and fnmatch(path, pattern):
                return True
        return False  # include set but no match
    return True


def render_history_markdown(file_path: str, commits: list[GitCommit]) -> str:
    """Render a file's commit history as a markdown document.

    Each commit becomes an H2 section with date, author, and message.
    """
    parts: list[str] = [f"# {file_path} — Change History\n"]

    for c in commits:
        # Date in readable format (strip time if present)
        date_short = c.date[:10] if len(c.date) >= 10 else c.date
        short_hash = c.hash[:7]

        parts.append(f"## {date_short}: {c.subject} ({short_hash})")
        author_line = f"Author: {c.author}"
        if c.author_email:
            author_line += f" <{c.author_email}>"
        parts.append(author_line + "\n")

        if c.body:
            parts.append(c.body)

        # List other files changed in the same commit (for cross-reference context)
        other_files = [f for f in c.files if f != file_path]
        if other_files:
            # Limit to avoid huge lists from bulk commits
            shown = other_files[:10]
            parts.append("Also changed: " + ", ".join(shown))
            if len(other_files) > 10:
                parts.append(f"  (+{len(other_files) - 10} more files)")

        parts.append("")  # blank line between commits

    return "\n".join(parts).strip()


def _content_hash(text: str) -> str:
    """Short SHA-256 hash for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _build_cross_file_links(
    commits: list[GitCommit],
    filtered: dict[str, list[GitCommit]],
    ingested_paths: set[str],
) -> dict[str, list[str]]:
    """Build cross-file links for files that share commits.

    Returns a dict mapping each git-history doc path to its related doc paths.
    Only includes paths that were actually ingested this run.
    """
    filtered_files = set(filtered.keys())
    links: dict[str, set[str]] = {}

    for commit in commits:
        # Files from this commit that are in our filtered set
        shared = [f for f in commit.files if f in filtered_files]
        if len(shared) < 2 or len(shared) > 20:
            # Skip bulk commits (>20 files) — they create O(N²) links with low signal
            continue

        # Create bidirectional links between all pairs
        for f in shared:
            doc_path = f"git-history/{f}"
            if doc_path not in ingested_paths:
                continue
            for other in shared:
                if other == f:
                    continue
                other_doc = f"git-history/{other}"
                if other_doc in ingested_paths:
                    links.setdefault(doc_path, set()).add(other_doc)

    return {k: sorted(v) for k, v in links.items()}


# ---------------------------------------------------------------------------
# Git subprocess helpers
# ---------------------------------------------------------------------------


def _git_log_format() -> str:
    """Build the --format string for git log."""
    return (
        f"{_COMMIT_SEP}%n"
        f"HASH:%H%n"
        f"AUTHOR:%an%n"
        f"EMAIL:%ae%n"
        f"DATE:%aI%n"
        f"SUBJECT:%s%n"
        f"{_BODY_START}%n%b%n{_BODY_END}%n"
        f"{_FILES_START}"
    )


async def _run_git_log(
    repo_path: str,
    config: GitIngestConfig,
) -> str:
    """Execute git log and return raw output."""
    cmd = [
        "git",
        "-C",
        repo_path,
        "log",
        f"--format={_git_log_format()}",
        "--name-only",
    ]

    if not config.merge_commits:
        cmd.append("--no-merges")

    if config.since:
        cmd.append(f"--since={config.since}")

    if config.until:
        cmd.append(f"--until={config.until}")

    if config.author:
        cmd.append(f"--author={config.author}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise RuntimeError(f"git log failed: {err}")

    return stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def ingest_git(
    gnosis_config: GnosisMcpConfig,
    repo_path: str,
    config: GitIngestConfig,
) -> list[GitIngestResult]:
    """Ingest git history from a repository into the documentation database.

    1. Run ``git log`` to get commit history
    2. Group commits by file
    3. Filter by include/exclude patterns
    4. Render each file's history as markdown
    5. Ingest via the existing backend pipeline

    Returns a list of results per file.
    """
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.ingest import chunk_by_headings

    # Validate repo path
    repo = Path(repo_path).resolve()
    if not (repo / ".git").exists() and not repo.name == ".git":
        raise ValueError(f"Not a git repository: {repo}")

    # Run git log
    raw_log = await _run_git_log(str(repo), config)
    commits = parse_git_log(raw_log)

    if not commits:
        return [
            GitIngestResult(
                path=str(repo),
                commits=0,
                chunks=0,
                action="skipped",
                detail="No commits found",
            )
        ]

    # Group by file and filter
    by_file = group_by_file(commits)
    results: list[GitIngestResult] = []

    # Filter and limit
    filtered: dict[str, list[GitCommit]] = {}
    for fp, file_commits in sorted(by_file.items()):
        if not should_include(fp, config.include, config.exclude):
            continue
        filtered[fp] = file_commits[: config.max_commits]

    if not filtered:
        return [
            GitIngestResult(
                path=str(repo),
                commits=0,
                chunks=0,
                action="skipped",
                detail="No files matched filters",
            )
        ]

    # Dry run — just report
    if config.dry_run:
        for fp, file_commits in filtered.items():
            doc_path = f"git-history/{fp}"
            md = render_history_markdown(fp, file_commits)
            chunks = chunk_by_headings(md, doc_path, max_chunk_size=gnosis_config.chunk_size)
            results.append(
                GitIngestResult(
                    path=doc_path,
                    commits=len(file_commits),
                    chunks=len(chunks),
                    action="dry-run",
                )
            )
        return results

    # Create backend and ingest
    backend = create_backend(gnosis_config)
    await backend.startup()

    try:
        # Auto-initialize schema
        table_name = gnosis_config.chunks_tables[0]
        table_exists = await backend.has_column(table_name, "file_path")
        if not table_exists:
            await backend.init_schema()

        has_hash = await backend.has_column(table_name, "content_hash")
        has_tags = await backend.has_column(table_name, "tags")

        total = len(filtered)
        for idx, (fp, file_commits) in enumerate(filtered.items(), 1):
            doc_path = f"git-history/{fp}"

            try:
                md = render_history_markdown(fp, file_commits)
                digest = _content_hash(md)

                # Skip unchanged (unless force re-ingest)
                if has_hash and not config.force:
                    existing = await backend.get_content_hash(doc_path)
                    if existing == digest:
                        doc_chunks = await backend.get_doc(doc_path)
                        results.append(
                            GitIngestResult(
                                path=doc_path,
                                commits=len(file_commits),
                                chunks=len(doc_chunks),
                                action="unchanged",
                            )
                        )
                        continue

                chunks = chunk_by_headings(md, doc_path, max_chunk_size=gnosis_config.chunk_size)

                count = await backend.ingest_file(
                    doc_path,
                    chunks,
                    title=f"History: {fp}",
                    category="git-history",
                    audience="developer",
                    tags=None,
                    content_hash=digest,
                    has_tags_col=has_tags,
                    has_hash_col=has_hash,
                )

                # Auto-link to the source file (if it exists in the DB)
                try:
                    await backend.insert_links(doc_path, [fp], relation_type="git_ref")
                except Exception:
                    pass  # links table may not exist

                results.append(
                    GitIngestResult(
                        path=doc_path,
                        commits=len(file_commits),
                        chunks=count,
                        action="ingested",
                    )
                )
                log.info(
                    "[%d/%d] %s (%d commits, %d chunks)",
                    idx,
                    total,
                    doc_path,
                    len(file_commits),
                    count,
                )

            except Exception as e:
                results.append(
                    GitIngestResult(
                        path=doc_path,
                        commits=0,
                        chunks=0,
                        action="error",
                        detail=str(e),
                    )
                )

        # Cross-file commit graph links
        # For files that share commits, create relates_to links between their docs
        ingested_paths = {r.path for r in results if r.action == "ingested"}
        if len(ingested_paths) > 1:
            try:
                cross_links = _build_cross_file_links(commits, filtered, ingested_paths)
                for source, targets in cross_links.items():
                    try:
                        await backend.insert_links(source, targets, relation_type="git_co_change")
                    except Exception:
                        pass  # links table may not exist
                if cross_links:
                    total_links = sum(len(t) for t in cross_links.values())
                    log.info(
                        "Cross-file links: %d sources, %d links", len(cross_links), total_links
                    )
            except Exception:
                log.debug("Cross-file link creation failed", exc_info=True)

        # Embed if requested
        if config.embed and any(r.action == "ingested" for r in results):
            try:
                from gnosis_mcp.embed import embed_pending

                provider = gnosis_config.embed_provider
                if not provider:
                    try:
                        import onnxruntime  # noqa: F401
                        import tokenizers  # noqa: F401

                        provider = "local"
                    except ImportError:
                        pass

                if provider:
                    model = gnosis_config.embed_model
                    if provider == "local" and not gnosis_config.embed_provider:
                        model = "MongoDB/mdbr-leaf-ir"

                    log.info("Embedding git history chunks (provider=%s)...", provider)
                    await embed_pending(
                        config=gnosis_config,
                        provider=provider,
                        model=model,
                        api_key=gnosis_config.embed_api_key,
                        url=gnosis_config.embed_url,
                        batch_size=gnosis_config.embed_batch_size,
                        dim=gnosis_config.embed_dim,
                    )
            except Exception as e:
                log.warning("Embedding failed: %s", e)

    finally:
        await backend.shutdown()

    return results
