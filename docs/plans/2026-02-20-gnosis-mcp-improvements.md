# Gnosis MCP Improvements — v0.7.8 through v0.8.0

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix bugs, improve search, add CLI features, CI improvements, optional format extras, and establish versioning practices.

**Architecture:** Each version is a self-contained commit: code changes + test updates + doc updates + 4-file version bump. Every version follows the same release checklist.

**Tech Stack:** Python 3.11+ stdlib, pytest, FTS5/SQLite, GitHub Actions CI

**Versioning Strategy:**
- **0.7.x** — Bug fixes + small features (no new deps)
- **0.8.0** — New optional dependencies (`[rst]`, `[pdf]`)
- **1.0.0** — When tool/resource API is stable + all formats working + 300+ tests

---

## Release Checklist (applies to EVERY version)

1. Bump version in 4 files: `pyproject.toml`, `src/gnosis_mcp/__init__.py`, `server.json` (2 places), `marketplace.json`
2. Update docs: `README.md`, `llms.txt`, `llms-full.txt`, `CLAUDE.md` as needed
3. Run `pytest tests/ -q` — all must pass
4. `git add` changed files, commit with `vX.Y.Z: description`
5. Push to all 3 remotes: `selify`, `codeberg`, `github`

---

## Task 1: v0.7.8 — Bug fixes + `--force` ingest

### Bug 1: Wire `GNOSIS_MCP_CHUNK_SIZE` to `chunk_by_headings`

**Files:**
- Modify: `src/gnosis_mcp/ingest.py` — `ingest_path()` lines ~543 and ~599
- Test: `tests/test_ingest.py`

**Problem:** `config.chunk_size` (from `GNOSIS_MCP_CHUNK_SIZE` env var) is parsed into config but never passed to `chunk_by_headings()` during file ingestion. The function defaults to 4000 internally.

**Step 1: Write failing test**

```python
class TestIngestChunkSize:
    def test_chunk_size_respected(self, tmp_path):
        """Tiny chunk_size should produce more chunks."""
        f = tmp_path / "big.md"
        f.write_text("# Big\n\n## A\n\n" + "word " * 200 + "\n\n## B\n\n" + "word " * 200)
        # Default (4000) should produce 2 chunks
        default = chunk_by_headings(f.read_text(), "big.md")
        # Small (100) should produce more
        small = chunk_by_headings(f.read_text(), "big.md", max_chunk_size=100)
        assert len(small) > len(default)
```

**Step 2: Fix `ingest_path` — pass `config.chunk_size`**

Add `max_chunk_size` parameter to `ingest_path`:

```python
async def ingest_path(
    config,
    root: str,
    *,
    dry_run: bool = False,
) -> list[IngestResult]:
```

Inside both the dry-run path and normal path, change:
```python
# dry-run (line ~543):
chunks = chunk_by_headings(body, str(f.relative_to(base)), config.chunk_size)

# normal (line ~599):
chunks = chunk_by_headings(body, rel, config.chunk_size)
```

### Bug 2: FTS5 snippet uses wrong column index

**Files:**
- Modify: `src/gnosis_mcp/sqlite_backend.py` — `_search_keyword()` line ~196
- Test: `tests/test_sqlite_backend.py` (if exists) or manual verification

**Problem:** `snippet(documentation_chunks_fts, 1, ...)` — column index 1 is `title`. Content is typically at index 2 or wherever it is in the FTS table. Need to verify FTS table column order.

**Step 1: Check FTS table definition**

Read `src/gnosis_mcp/sqlite_schema.py` — find the `CREATE VIRTUAL TABLE ... USING fts5(...)` statement. The column order determines the index.

**Step 2: Fix if wrong, or document if intentional**

If FTS5 columns are `(file_path, title, content, ...)` then:
- Index 0 = file_path
- Index 1 = title (current — highlights title matches)
- Index 2 = content (probably what we want — highlights content matches)

Change to `snippet(documentation_chunks_fts, 2, ...)` if content is at index 2.

### Feature: `--force` flag for ingest

**Files:**
- Modify: `src/gnosis_mcp/ingest.py` — `ingest_path()` add `force: bool = False` parameter
- Modify: `src/gnosis_mcp/cli.py` — add `--force` arg to ingest subparser
- Test: `tests/test_ingest.py`

**Step 1: Add `--force` to CLI**

```python
p_ingest.add_argument("--force", action="store_true", help="Re-ingest all files, ignoring content hash")
```

Pass `force=args.force` to `ingest_path()`.

**Step 2: Add `force` parameter to `ingest_path`**

```python
async def ingest_path(config, root: str, *, dry_run: bool = False, force: bool = False):
```

In the hash-check block:
```python
if has_hash and not force:
    existing = await backend.get_content_hash(rel)
    if existing == digest:
        ...
        continue
```

**Step 3: Write test**

```python
class TestIngestForce:
    async def test_force_reingests_unchanged(self, tmp_path):
        """With force=True, unchanged files should still be re-ingested."""
        # Would need a mock backend — verify that force skips the hash check
```

**Step 4: Commit as v0.7.8**

---

## Task 2: v0.7.9 — Better FTS5 multi-word search

**Files:**
- Modify: `src/gnosis_mcp/sqlite_backend.py` — `_to_fts5_query()`
- Test: `tests/test_sqlite_backend.py`

**Problem:** `"pandas data analysis"` returns 0 results because FTS5 uses implicit AND for space-separated terms. All 3 words must appear in the same chunk. For docs search, OR is often more useful — find chunks with ANY matching word, ranked by relevance.

**Approach:** Use FTS5 `OR` operator between terms. BM25 ranking still puts multi-match results first.

**Step 1: Write failing test**

```python
def test_fts5_query_uses_or():
    """Multi-word queries should use OR for broader matching."""
    result = _to_fts5_query("pandas data analysis")
    assert "OR" in result
    # Should be: "pandas" OR "data" OR "analysis"
```

**Step 2: Update `_to_fts5_query`**

```python
def _to_fts5_query(text: str) -> str:
    words = text.split()
    if not words:
        return '""'
    safe = []
    for w in words:
        cleaned = _FTS5_SPECIAL.sub("", w)
        if cleaned:
            safe.append(f'"{cleaned}"')
    if not safe:
        return '""'
    return " OR ".join(safe) if len(safe) > 1 else safe[0]
```

**Step 3: Verify multi-word search works**

```bash
gnosis-mcp search "pandas data analysis"
# Should now return analysis.ipynb
```

**Step 4: Commit as v0.7.9**

---

## Task 3: v0.7.10 — Export CSV + `gnosis-mcp diff`

### Feature: Export CSV format

**Files:**
- Modify: `src/gnosis_mcp/cli.py` — `cmd_export()` and export format choices
- Test: `tests/test_cli.py` (if exists)

**Step 1: Add "csv" to export format choices**

```python
p_export.add_argument(
    "-f", "--format", choices=["json", "markdown", "csv"], default="json",
    help="Output format (default: json)"
)
```

**Step 2: Add CSV export logic in `cmd_export`**

```python
elif args.format == "csv":
    import csv as csv_mod
    import io
    writer = csv_mod.writer(sys.stdout)
    writer.writerow(["file_path", "title", "category", "chunks"])
    for doc in docs:
        writer.writerow([doc["file_path"], doc["title"], doc.get("category", ""), doc.get("chunks", 0)])
```

### Feature: `gnosis-mcp diff` command

**Files:**
- Modify: `src/gnosis_mcp/cli.py` — add `diff` subcommand
- Modify: `src/gnosis_mcp/ingest.py` — add `diff_path()` function

**Purpose:** Show what would change on re-ingest — new files, modified files, deleted files (in DB but not on disk).

**Step 1: Add `diff` subparser**

```python
p_diff = sub.add_parser("diff", help="Show what would change on re-ingest")
p_diff.add_argument("path", help="File or directory to compare")
```

**Step 2: Implement `diff_path()` in ingest.py**

```python
async def diff_path(config, root: str) -> dict[str, list[str]]:
    """Compare filesystem files with database state.
    Returns {"new": [...], "modified": [...], "deleted": [...]}.
    """
```

Logic:
1. `scan_files(root)` → get all files on disk
2. Query DB for all stored `file_path` values
3. For each file on disk: compute `content_hash()`, compare with stored hash
4. Files on disk but not in DB → "new"
5. Files in DB with different hash → "modified"
6. Files in DB but not on disk → "deleted"
7. Files with matching hash → skip (unchanged)

**Step 3: Commit as v0.7.10**

---

## Task 4: v0.7.11 — GitHub Releases + ingest progress

### Feature: GitHub Releases in CI

**Files:**
- Modify: `.github/workflows/publish.yml` — add release job

**Step 1: Add `release` job after `tag` job**

```yaml
  github-release:
    needs: [check, tag]
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          TAG="${{ needs.check.outputs.version }}"
          gh release create "$TAG" \
            --title "$TAG" \
            --generate-notes \
            --latest
```

### Feature: Ingest progress output

**Files:**
- Modify: `src/gnosis_mcp/cli.py` — `cmd_ingest()` progress display

**Step 1: Add file count to ingest output**

In `cmd_ingest`, after scanning but before ingesting, print total file count:
```python
# Before ingest loop, log total
log.info("Found %d files to process", len(results))
```

Actually, `ingest_path` handles the loop internally. The progress should be added inside `ingest_path` or by modifying the CLI to show a running counter.

Simple approach: add a progress callback or just log the counter:

```python
# In ingest_path, inside the file loop, after processing each file:
log.info("[%d/%d] %s: %s (%d chunks)", idx + 1, total, action, rel, count)
```

**Step 2: Commit as v0.7.11**

---

## Task 5: v0.8.0 — Optional format extras (`[rst]`, `[pdf]`)

**Files:**
- Modify: `pyproject.toml` — add `[rst]` and `[pdf]` optional extras
- Modify: `src/gnosis_mcp/ingest.py` — add RST and PDF converters, update `_SUPPORTED_EXTS`
- Test: `tests/test_ingest.py`

### RST support (`[rst]` extra → `docutils`)

**Step 1: Add optional extra in pyproject.toml**

```toml
rst = ["docutils>=0.20"]
pdf = ["pypdf>=4.0"]
formats = ["docutils>=0.20", "pypdf>=4.0"]
```

**Step 2: Add `.rst` converter**

```python
def _convert_rst(text: str, file_path: Path) -> str:
    """reStructuredText: convert to HTML via docutils, then strip tags."""
    try:
        from docutils.core import publish_parts
        parts = publish_parts(text, writer_name="html")
        html = parts["html_body"]
        # Strip HTML tags to get plain text, preserve structure
        import re
        # Convert <h2> to ## etc, <p> to paragraphs
        clean = re.sub(r"<h(\d)[^>]*>(.*?)</h\1>", lambda m: "#" * int(m.group(1)) + " " + m.group(2), html)
        clean = re.sub(r"<[^>]+>", "", clean)
        return clean.strip()
    except ImportError:
        # docutils not installed — return as plain text
        return f"# {file_path.stem}\n\n{text}"
```

**Step 3: Add `.pdf` converter**

```python
def _convert_pdf(text_bytes: bytes, file_path: Path) -> str:
    """PDF: extract text via pypdf."""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(text_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            content = page.extract_text() or ""
            if content.strip():
                pages.append(f"## Page {i + 1}\n\n{content}")
        return f"# {file_path.stem}\n\n" + "\n\n".join(pages) if pages else ""
    except ImportError:
        return ""  # Skip PDF if pypdf not installed
```

**Note:** PDF files are binary, not text. `ingest_path` currently reads with `read_text()`. Need to handle binary reads for `.pdf`:

```python
if f.suffix.lower() == ".pdf":
    raw = f.read_bytes()
    text = _convert_pdf(raw, f)
else:
    text = f.read_text(encoding="utf-8", errors="replace")
```

**Step 4: Update `_SUPPORTED_EXTS`**

Change from hardcoded frozenset to dynamic:
```python
_BASE_EXTS = frozenset({".md", ".txt", ".ipynb", ".toml", ".csv", ".json"})

def _supported_exts() -> frozenset[str]:
    exts = set(_BASE_EXTS)
    try:
        import docutils  # noqa: F401
        exts.add(".rst")
    except ImportError:
        pass
    try:
        import pypdf  # noqa: F401
        exts.add(".pdf")
    except ImportError:
        pass
    return frozenset(exts)

_SUPPORTED_EXTS = _supported_exts()
```

**Step 5: Write tests**

Tests should work without the optional deps (graceful degradation):
```python
class TestConvertRst:
    def test_rst_without_docutils(self):
        """Without docutils, RST files treated as plain text."""
        # Mock docutils import failure
        ...

    def test_rst_with_docutils(self):
        """With docutils, RST converted to markdown-like text."""
        pytest.importorskip("docutils")
        result = _convert_rst("Title\n=====\n\nParagraph.", Path("doc.rst"))
        assert "Title" in result
```

**Step 6: Commit as v0.8.0**

---

## Task 6: v0.8.1 — CHANGELOG.md + versioning rules + MCP Registry fix

### Create CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`

Format:
```markdown
# Changelog

## [0.8.1] - 2026-02-XX
### Added
- CHANGELOG.md
- Versioning rules in CLAUDE.md

## [0.8.0] - 2026-02-XX
### Added
- Optional RST support via `[rst]` extra (docutils)
- Optional PDF support via `[pdf]` extra (pypdf)
- Combined `[formats]` extra for both

## [0.7.11] - 2026-02-XX
...
```

Backfill from git log for v0.7.0 through v0.8.0.

### Add versioning rules to CLAUDE.md

Add section:
```markdown
## Versioning

Semantic versioning (pre-1.0):
- **Patch (0.7.x → 0.7.y)**: Bug fixes, small features, no new required deps
- **Minor (0.7.x → 0.8.0)**: New optional deps, significant features, CLI changes
- **Major (→ 1.0.0)**: Stable tool/resource API, 300+ tests, all doc formats working

Every version commit MUST:
1. Bump 4 version files (pyproject.toml, __init__.py, server.json, marketplace.json)
2. Update relevant docs (README, llms.txt, llms-full.txt, CLAUDE.md)
3. Update CHANGELOG.md with what changed
4. All tests passing
```

### Investigate MCP Registry failure

Check `mcp-publisher publish` error. Likely needs:
- Correct `server.json` schema version
- OIDC audience configuration for MCP Registry
- May need to file an issue with the MCP Registry team

### Verify llms.txt completeness

Audit `llms.txt` against the [llms.txt specification](https://llmstxt.org/):
- Ensure all tools, resources, config vars documented
- Ensure install instructions are clear
- Ensure editor config examples are current
- Cross-check with `llms-full.txt` for consistency

**Step: Commit as v0.8.1**

---

## Summary

| Version | Theme | New Deps | Est. Tests Added |
|---------|-------|----------|-----------------|
| v0.7.8 | Bug fixes + --force | None | ~5 |
| v0.7.9 | Better FTS5 search | None | ~3 |
| v0.7.10 | Export CSV + diff cmd | None | ~6 |
| v0.7.11 | GitHub Releases + progress | None | ~2 |
| v0.8.0 | RST + PDF formats | docutils, pypdf (optional) | ~8 |
| v0.8.1 | CHANGELOG + versioning rules | None | 0 |

Total: ~6 versions, ~24 new tests, targeting 290+ total.
