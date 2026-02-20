"""File ingestion: scan files, convert to markdown, chunk by headings, load into database.

Supported formats (zero third-party dependencies):
- .md  — Markdown (native, pass-through)
- .txt — Plain text (wrapped with H1 title)
- .ipynb — Jupyter notebooks (stdlib json, markdown + code cells)
- .toml — TOML config files (stdlib tomllib, sections per top-level key)
- .csv  — CSV data (stdlib csv, rendered as markdown table)
- .json — JSON documents (stdlib json, top-level keys as H2 sections)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import tomllib
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
    "diff_path",
]

log = logging.getLogger("gnosis_mcp")

_SUPPORTED_EXTS = frozenset({".md", ".txt", ".ipynb", ".toml", ".csv", ".json"})

# Frontmatter key: value parser (no yaml dependency)
_FM_KV_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)
_H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{2,4}) (.+)$", re.MULTILINE)
_FENCED_CODE_RE = re.compile(r"^(`{3,}|~{3,})", re.MULTILINE)


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


def _find_protected_ranges(text: str) -> list[tuple[int, int]]:
    """Find byte ranges of fenced code blocks and tables that must not be split."""
    ranges: list[tuple[int, int]] = []

    # Fenced code blocks: ``` or ~~~
    in_fence = False
    fence_start = 0
    fence_marker = ""
    for match in _FENCED_CODE_RE.finditer(text):
        marker = match.group(1)
        if not in_fence:
            in_fence = True
            fence_start = match.start()
            fence_marker = marker[0]  # ` or ~
        elif marker[0] == fence_marker:
            ranges.append((fence_start, match.end()))
            in_fence = False
    # Unclosed fence — protect to end
    if in_fence:
        ranges.append((fence_start, len(text)))

    # Tables: consecutive lines starting with |
    lines = text.split("\n")
    pos = 0
    table_start = -1
    for line in lines:
        stripped = line.strip()
        is_table = stripped.startswith("|") and stripped.endswith("|")
        if is_table and table_start == -1:
            table_start = pos
        elif not is_table and table_start != -1:
            ranges.append((table_start, pos))
            table_start = -1
        pos += len(line) + 1  # +1 for \n
    if table_start != -1:
        ranges.append((table_start, len(text)))

    return sorted(ranges)


def _is_in_protected(pos: int, ranges: list[tuple[int, int]]) -> bool:
    """Check if a position falls inside any protected range."""
    for start, end in ranges:
        if start <= pos < end:
            return True
        if start > pos:
            break
    return False


def _split_paragraphs_safe(text: str, max_size: int) -> list[str]:
    """Split text at paragraph boundaries, never inside code blocks or tables."""
    if len(text) <= max_size:
        return [text]

    protected = _find_protected_ranges(text)

    # Find safe split points (double-newline positions outside protected ranges)
    split_points: list[int] = []
    idx = 0
    while True:
        idx = text.find("\n\n", idx)
        if idx == -1:
            break
        if not _is_in_protected(idx, protected):
            split_points.append(idx)
        idx += 2

    if not split_points:
        # No safe splits — return as-is (better too large than broken)
        return [text]

    # Build segments between split points
    boundaries = [0] + [sp + 2 for sp in split_points] + [len(text)]
    segments = [text[boundaries[i]:boundaries[i + 1]] for i in range(len(boundaries) - 1)]

    # Greedily pack segments into chunks
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for seg in segments:
        seg_len = len(seg)
        if current_parts and current_len + seg_len > max_size:
            chunk_text = "".join(current_parts).strip()
            if chunk_text:
                chunks.append(chunk_text)
            current_parts = [seg]
            current_len = seg_len
        else:
            current_parts.append(seg)
            current_len += seg_len

    if current_parts:
        chunk_text = "".join(current_parts).strip()
        if chunk_text:
            chunks.append(chunk_text)

    return chunks if chunks else [text]


def _split_section_by_subheadings(
    content: str, doc_title: str, parent_title: str, level: int, max_size: int
) -> list[dict]:
    """Split an oversized section by sub-headings (H3 inside H2, etc.)."""
    sub_re = re.compile(rf"^{'#' * (level + 1)} (.+)$", re.MULTILINE)
    matches = list(sub_re.finditer(content))

    if not matches:
        # No sub-headings — split by paragraphs
        parts = _split_paragraphs_safe(content, max_size)
        if len(parts) == 1:
            return [{"title": parent_title, "content": content.strip(), "section_path": f"{doc_title} > {parent_title}"}]
        return [
            {
                "title": parent_title if i == 0 else f"{parent_title} (cont.)",
                "content": p,
                "section_path": f"{doc_title} > {parent_title}",
            }
            for i, p in enumerate(parts) if p.strip()
        ]

    chunks = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section = content[start:end].strip()

        if len(section) < 20:
            continue

        if len(section) > max_size and level + 1 < 4:
            # Recurse deeper
            chunks.extend(_split_section_by_subheadings(section, doc_title, title, level + 1, max_size))
        elif len(section) > max_size:
            # Deepest level — split by paragraphs
            parts = _split_paragraphs_safe(section, max_size)
            for j, p in enumerate(parts):
                if not p.strip():
                    continue
                chunks.append({
                    "title": title if j == 0 else f"{title} (cont.)",
                    "content": p,
                    "section_path": f"{doc_title} > {title}",
                })
        else:
            chunks.append({"title": title, "content": section, "section_path": f"{doc_title} > {title}"})

    return chunks


def chunk_by_headings(markdown: str, file_path: str, max_chunk_size: int = 4000) -> list[dict]:
    """Split markdown into chunks by headings with structure-aware boundaries.

    Strategy:
    1. Split at H2 boundaries (primary)
    2. Oversized H2 sections split at H3, then H4
    3. Still too large: split at paragraph boundaries
    4. Never splits inside fenced code blocks or tables
    5. No headings: paragraph-based recursive splitting

    Returns list of {"title", "content", "section_path"}.
    """
    matches = list(_H2_RE.finditer(markdown))
    doc_title = extract_title(markdown) or Path(file_path).stem

    if not matches:
        # No H2 headers — try paragraph splitting if oversized
        stripped = markdown.strip()
        if len(stripped) <= max_chunk_size:
            return [{"title": doc_title, "content": stripped, "section_path": doc_title}]
        parts = _split_paragraphs_safe(stripped, max_chunk_size)
        return [
            {
                "title": doc_title if i == 0 else f"{doc_title} (cont.)",
                "content": p,
                "section_path": doc_title,
            }
            for i, p in enumerate(parts) if p.strip()
        ] or [{"title": doc_title, "content": stripped, "section_path": doc_title}]

    chunks = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()

        if len(content) < 20:
            continue

        if len(content) > max_chunk_size:
            # Oversized — try sub-heading split
            chunks.extend(_split_section_by_subheadings(content, doc_title, title, 2, max_chunk_size))
        else:
            chunks.append({
                "title": title,
                "content": content,
                "section_path": f"{doc_title} > {title}",
            })

    return chunks or [{"title": doc_title, "content": markdown.strip(), "section_path": doc_title}]


def _convert_to_markdown(text: str, file_path: Path) -> str:
    """Convert supported file formats to markdown for chunking.  No-op for .md."""
    ext = file_path.suffix.lower()
    if ext == ".md":
        return text
    if ext == ".txt":
        return _convert_txt(text, file_path)
    if ext == ".ipynb":
        return _convert_ipynb(text, file_path)
    if ext == ".toml":
        return _convert_toml(text, file_path)
    if ext == ".csv":
        return _convert_csv(text, file_path)
    if ext == ".json":
        return _convert_json(text, file_path)
    return text


def _convert_txt(text: str, file_path: Path) -> str:
    """Plain text: add H1 title from filename."""
    title = file_path.stem.replace("-", " ").replace("_", " ").title()
    return f"# {title}\n\n{text}"


def _convert_ipynb(text: str, file_path: Path) -> str:
    """Jupyter notebook: extract markdown + code cells."""
    try:
        nb = json.loads(text)
    except (ValueError, KeyError):
        return text

    cells = nb.get("cells", [])
    if not cells:
        return text

    # Detect kernel language for code fences
    meta = nb.get("metadata", {})
    lang = meta.get("kernelspec", {}).get("language", "") or meta.get(
        "language_info", {}
    ).get("name", "")

    parts: list[str] = []
    for cell in cells:
        cell_type = cell.get("cell_type", "")
        source = cell.get("source", [])
        if isinstance(source, list):
            source = "".join(source)
        source = source.strip()
        if not source:
            continue

        if cell_type == "markdown":
            parts.append(source)
        elif cell_type == "code":
            parts.append(f"```{lang}\n{source}\n```")
        elif cell_type == "raw":
            parts.append(source)

    return "\n\n".join(parts) if parts else text


def _convert_toml(text: str, file_path: Path) -> str:
    """TOML: render top-level keys as H2 sections."""
    try:
        data = tomllib.loads(text)
    except Exception:
        return f"# {file_path.name}\n\n```toml\n{text}\n```"

    parts: list[str] = [f"# {file_path.name}"]

    for key, value in data.items():
        if isinstance(value, dict):
            parts.append(f"## {key}")
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    parts.append(f"**{k}**:\n```\n{json.dumps(v, indent=2)}\n```")
                else:
                    parts.append(f"- **{k}**: {v}")
        elif isinstance(value, list):
            parts.append(f"## {key}")
            for item in value:
                if isinstance(item, dict):
                    line = ", ".join(f"{k}={v}" for k, v in item.items())
                    parts.append(f"- {line}")
                else:
                    parts.append(f"- {item}")
        else:
            parts.append(f"- **{key}**: {value}")

    return "\n\n".join(parts)


def _convert_csv(text: str, file_path: Path) -> str:
    """CSV: render as markdown table."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return text

    header = rows[0]
    ncols = len(header)
    lines = [
        f"# {file_path.stem}",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows[1:]:
        padded = (row + [""] * ncols)[:ncols]
        lines.append("| " + " | ".join(padded) + " |")

    return "\n".join(lines)


def _convert_json(text: str, file_path: Path) -> str:
    """JSON: top-level dict keys as H2 sections, arrays as code block."""
    try:
        data = json.loads(text)
    except ValueError:
        return text

    if isinstance(data, dict) and data:
        parts: list[str] = [f"# {file_path.name}"]
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, indent=2)
                parts.append(f"## {key}\n\n```json\n{rendered}\n```")
            else:
                parts.append(f"- **{key}**: {value}")
        return "\n\n".join(parts)

    return f"# {file_path.name}\n\n```json\n{json.dumps(data, indent=2)}\n```"


def scan_files(root: Path) -> list[Path]:
    """Recursively find all supported files under root, sorted."""
    if root.is_file() and root.suffix.lower() in _SUPPORTED_EXTS:
        return [root]
    found: list[Path] = []
    for ext in _SUPPORTED_EXTS:
        found.extend(root.rglob(f"*{ext}"))
    return sorted(set(found))


async def ingest_path(
    config,
    root: str,
    *,
    dry_run: bool = False,
    force: bool = False,
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
        return [IngestResult(path=root, chunks=0, action="skipped", detail="No supported files found")]

    # Determine base for relative paths
    base = root_path.parent if root_path.is_file() else root_path

    results: list[IngestResult] = []

    if dry_run:
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            if len(text.strip()) < 50:
                results.append(IngestResult(path=str(f.relative_to(base)), chunks=0, action="skipped", detail="Too small (<50 chars)"))
                continue
            md_text = _convert_to_markdown(text, f)
            _, body = parse_frontmatter(md_text)
            chunks = chunk_by_headings(body, str(f.relative_to(base)), max_chunk_size=config.chunk_size)
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

            # Hash original text for change detection, then convert format
            digest = content_hash(text)
            md_text = _convert_to_markdown(text, f)

            # Parse frontmatter
            frontmatter, body = parse_frontmatter(md_text)

            # Skip unchanged files (unless force re-ingest)
            if has_hash and not force:
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
            chunks = chunk_by_headings(body, rel, max_chunk_size=config.chunk_size)

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


async def diff_path(config, root: str) -> dict[str, list[str]]:
    """Compare filesystem files with database state.

    Returns {"new": [...], "modified": [...], "deleted": [...], "unchanged": [...]}.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        return {"new": [], "modified": [], "deleted": [], "unchanged": []}

    files = scan_files(root_path)
    base = root_path.parent if root_path.is_file() else root_path

    from gnosis_mcp.backend import create_backend

    backend = create_backend(config)
    await backend.startup()

    try:
        # Check if table exists
        table_name = config.chunks_tables[0]
        has_hash = await backend.has_column(table_name, "content_hash")

        # Get all stored file paths and hashes
        docs = await backend.list_docs()
        db_paths = {d["file_path"] for d in docs}

        # Build hash map from DB
        db_hashes: dict[str, str | None] = {}
        if has_hash:
            for d in docs:
                h = await backend.get_content_hash(d["file_path"])
                db_hashes[d["file_path"]] = h

        # Classify files
        new: list[str] = []
        modified: list[str] = []
        unchanged: list[str] = []

        disk_paths: set[str] = set()
        for f in files:
            rel = str(f.relative_to(base))
            disk_paths.add(rel)

            if rel not in db_paths:
                new.append(rel)
            elif has_hash:
                text = f.read_text(encoding="utf-8", errors="replace")
                digest = content_hash(text)
                if db_hashes.get(rel) != digest:
                    modified.append(rel)
                else:
                    unchanged.append(rel)
            else:
                # No hash column — can't detect modifications, treat as unchanged
                unchanged.append(rel)

        # Files in DB but not on disk
        deleted = sorted(db_paths - disk_paths)

        return {
            "new": sorted(new),
            "modified": sorted(modified),
            "deleted": sorted(deleted),
            "unchanged": sorted(unchanged),
        }
    finally:
        await backend.shutdown()
