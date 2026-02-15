"""File ingestion: scan markdown files, chunk by headings, load into PostgreSQL."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "IngestResult",
    "content_hash",
    "parse_frontmatter",
    "extract_title",
    "chunk_by_headings",
    "scan_files",
    "ingest_path",
]

log = logging.getLogger("gnosis_mcp")

# Frontmatter key: value parser (no yaml dependency)
_FM_KV_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)
_H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)


@dataclass
class IngestResult:
    """Result of ingesting a single file."""

    path: str
    chunks: int
    action: str  # "ingested", "unchanged", "skipped", "error"
    detail: str = ""


def content_hash(text: str) -> str:
    """Short SHA-256 hash for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    """Parse YAML-like frontmatter without a yaml dependency.

    Supports simple ``key: value`` pairs (strings only).
    Returns (metadata_dict, body_without_frontmatter).
    """
    if not markdown.startswith("---"):
        return {}, markdown

    end = markdown.find("\n---", 3)
    if end == -1:
        return {}, markdown

    fm_block = markdown[4:end]
    body = markdown[end + 4 :].lstrip("\n")

    meta: dict[str, str] = {}
    for match in _FM_KV_RE.finditer(fm_block):
        key, val = match.group(1).strip(), match.group(2).strip().strip("\"'")
        meta[key] = val

    return meta, body


def extract_title(markdown: str) -> str | None:
    """Extract the first H1 heading from markdown."""
    hit = _H1_RE.search(markdown)
    return hit.group(1).strip() if hit else None


def chunk_by_headings(markdown: str, file_path: str) -> list[dict]:
    """Split markdown into chunks by H2 headers.

    Returns list of {"title", "content", "section_path"}.
    Falls back to paragraph chunking if no H2 headers found.
    """
    matches = list(_H2_RE.finditer(markdown))
    doc_title = extract_title(markdown) or Path(file_path).stem

    if not matches:
        # No H2 headers — return whole doc as one chunk
        return [{"title": doc_title, "content": markdown.strip(), "section_path": doc_title}]

    chunks = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()

        if len(content) < 20:
            continue

        chunks.append({
            "title": title,
            "content": content,
            "section_path": f"{doc_title} > {title}",
        })

    return chunks or [{"title": doc_title, "content": markdown.strip(), "section_path": doc_title}]


def scan_files(root: Path) -> list[Path]:
    """Recursively find all .md files under root, sorted."""
    if root.is_file() and root.suffix == ".md":
        return [root]
    return sorted(root.rglob("*.md"))


async def ingest_path(
    database_url: str,
    root: str,
    *,
    schema: str = "public",
    chunks_table: str = "documentation_chunks",
    dry_run: bool = False,
) -> list[IngestResult]:
    """Scan a path for markdown files and load them into PostgreSQL.

    Args:
        database_url: PostgreSQL connection string.
        root: File or directory path to ingest.
        schema: Database schema name.
        chunks_table: Target chunks table name.
        dry_run: If True, scan and report but don't write.

    Returns:
        List of IngestResult for each file processed.
    """
    import asyncpg

    root_path = Path(root).resolve()
    if not root_path.exists():
        return [IngestResult(path=root, chunks=0, action="error", detail="Path does not exist")]

    files = scan_files(root_path)
    if not files:
        return [IngestResult(path=root, chunks=0, action="skipped", detail="No .md files found")]

    # Determine base for relative paths
    base = root_path.parent if root_path.is_file() else root_path

    results: list[IngestResult] = []

    if dry_run:
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            if len(text.strip()) < 50:
                results.append(IngestResult(path=str(f.relative_to(base)), chunks=0, action="skipped", detail="Too small (<50 chars)"))
                continue
            _, body = parse_frontmatter(text)
            chunks = chunk_by_headings(body, str(f.relative_to(base)))
            results.append(IngestResult(path=str(f.relative_to(base)), chunks=len(chunks), action="dry-run"))
        return results

    qualified_table = f"{schema}.{chunks_table}"
    conn = await asyncpg.connect(database_url)

    try:
        # Check for content_hash column (optional, for skip-if-unchanged)
        has_hash = await conn.fetchval(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.columns"
            "  WHERE table_schema = $1 AND table_name = $2 AND column_name = 'content_hash'"
            ")",
            schema,
            chunks_table,
        )

        for f in files:
            rel = str(f.relative_to(base))
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                results.append(IngestResult(path=rel, chunks=0, action="error", detail=str(e)))
                continue

            if len(text.strip()) < 50:
                results.append(IngestResult(path=rel, chunks=0, action="skipped", detail="Too small"))
                continue

            # Parse frontmatter
            frontmatter, body = parse_frontmatter(text)
            digest = content_hash(text)

            # Skip unchanged files
            if has_hash:
                existing = await conn.fetchval(
                    f"SELECT content_hash FROM {qualified_table} WHERE file_path = $1 LIMIT 1",
                    rel,
                )
                if existing == digest:
                    # Count existing chunks for reporting
                    count = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {qualified_table} WHERE file_path = $1", rel
                    )
                    results.append(IngestResult(path=rel, chunks=count, action="unchanged"))
                    continue

            # Extract metadata
            title = extract_title(body) or frontmatter.get("title") or f.stem
            category = frontmatter.get("category") or (f.parent.name if f.parent != base else "general")
            audience = frontmatter.get("audience", "all")
            tags_str = frontmatter.get("tags", "")
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None

            # Chunk
            chunks = chunk_by_headings(body, rel)

            # Write in a transaction
            async with conn.transaction():
                await conn.execute(f"DELETE FROM {qualified_table} WHERE file_path = $1", rel)
                for i, chunk in enumerate(chunks):
                    cols = "file_path, chunk_index, title, content, category, audience"
                    vals = "$1, $2, $3, $4, $5, $6"
                    params: list = [rel, i, chunk["title"], chunk["content"], category, audience]
                    idx = 7

                    # Optional columns
                    col_check = await conn.fetchval(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM information_schema.columns"
                        "  WHERE table_schema = $1 AND table_name = $2 AND column_name = 'tags'"
                        ")",
                        schema,
                        chunks_table,
                    )
                    if col_check and tags:
                        cols += ", tags"
                        vals += f", ${idx}"
                        params.append(tags)
                        idx += 1

                    if has_hash:
                        cols += ", content_hash"
                        vals += f", ${idx}"
                        params.append(digest)
                        idx += 1

                    await conn.execute(
                        f"INSERT INTO {qualified_table} ({cols}) VALUES ({vals})",
                        *params,
                    )

            results.append(IngestResult(path=rel, chunks=len(chunks), action="ingested"))
            log.info("ingested: %s (%d chunks)", rel, len(chunks))

    finally:
        await conn.close()

    return results
