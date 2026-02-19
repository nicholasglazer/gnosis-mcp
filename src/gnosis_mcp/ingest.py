"""File ingestion: scan markdown files, chunk by headings, load into database."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "IngestResult",
    "content_hash",
    "parse_frontmatter",
    "extract_relates_to",
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


def extract_relates_to(markdown: str) -> list[str]:
    """Extract ``relates_to`` paths from frontmatter.

    Supports two formats:

    Comma-separated::

        relates_to: guides/setup.md, architecture/overview.md

    YAML list::

        relates_to:
          - guides/setup.md
          - architecture/overview.md

    Skips glob patterns (containing ``*`` or ``?``).
    Returns a list of clean path strings.
    """
    if not markdown.startswith("---"):
        return []

    end = markdown.find("\n---", 3)
    if end == -1:
        return []

    fm_block = markdown[4:end]
    lines = fm_block.split("\n")

    paths: list[str] = []
    in_list = False

    for line in lines:
        # Check for "relates_to: value" (inline comma-separated)
        match = re.match(r"^relates_to\s*:\s*(.+)$", line)
        if match:
            val = match.group(1).strip()
            if val:
                # Comma-separated values on the same line
                for v in val.split(","):
                    v = v.strip().strip("\"'- ")
                    if v:
                        paths.append(v)
                in_list = False
                continue

        # Check for "relates_to:" with no value (YAML list header)
        if re.match(r"^relates_to\s*:\s*$", line):
            in_list = True
            continue

        # Parse YAML list items
        if in_list:
            item_match = re.match(r"^\s+-\s+(.+)$", line)
            if item_match:
                v = item_match.group(1).strip().strip("\"'")
                if v:
                    paths.append(v)
            elif line.strip():
                # Non-empty, non-list line: end of list
                in_list = False

    # Filter out glob patterns
    return [p for p in paths if "*" not in p and "?" not in p]


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
    config,
    root: str,
    *,
    dry_run: bool = False,
) -> list[IngestResult]:
    """Scan a path for markdown files and load them into the database.

    Args:
        config: GnosisMcpConfig instance.
        root: File or directory path to ingest.
        dry_run: If True, scan and report but don't write.

    Returns:
        List of IngestResult for each file processed.
    """
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

    from gnosis_mcp.backend import create_backend

    backend = create_backend(config)
    await backend.startup()

    try:
        # Auto-initialize schema if tables don't exist (zero-config experience)
        table_exists = await backend.has_column(config.chunks_tables[0], "file_path")
        if not table_exists:
            await backend.init_schema()

        # Check for optional columns once before the file loop
        table_name = config.chunks_tables[0]
        has_hash = await backend.has_column(table_name, "content_hash")
        has_tags = await backend.has_column(table_name, "tags")

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
                existing = await backend.get_content_hash(rel)
                if existing == digest:
                    # Count existing chunks — use get_doc for chunk count
                    doc_chunks = await backend.get_doc(rel)
                    results.append(IngestResult(path=rel, chunks=len(doc_chunks), action="unchanged"))
                    continue

            # Extract metadata
            title = extract_title(body) or frontmatter.get("title") or f.stem
            category = frontmatter.get("category") or (f.parent.name if f.parent != base else "general")
            audience = frontmatter.get("audience", "all")
            tags_str = frontmatter.get("tags", "")
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None

            # Chunk
            chunks = chunk_by_headings(body, rel)

            # Write via backend
            count = await backend.ingest_file(
                rel,
                chunks,
                title=title,
                category=category,
                audience=audience,
                tags=tags,
                content_hash=digest,
                has_tags_col=has_tags,
                has_hash_col=has_hash,
            )

            # Extract and insert frontmatter links
            link_targets = extract_relates_to(text)
            if link_targets:
                try:
                    inserted = await backend.insert_links(rel, link_targets)
                    log.info("links: %s -> %d targets", rel, inserted)
                except Exception:
                    log.debug("insert_links failed for %s (links table may not exist)", rel)

            results.append(IngestResult(path=rel, chunks=count, action="ingested"))
            log.info("ingested: %s (%d chunks)", rel, count)

    finally:
        await backend.shutdown()

    return results
