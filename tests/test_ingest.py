"""Tests for gnosis_mcp.ingest — file scanning, frontmatter, chunking."""

from pathlib import Path

import pytest

from gnosis_mcp.ingest import (
    chunk_by_headings,
    content_hash,
    extract_title,
    parse_frontmatter,
    scan_files,
)


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self):
        assert content_hash("hello") == content_hash("hello")

    def test_different_content(self):
        assert content_hash("a") != content_hash("b")

    def test_length(self):
        assert len(content_hash("test")) == 16


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("# Title\n\nContent")
        assert meta == {}
        assert body == "# Title\n\nContent"

    def test_basic_frontmatter(self):
        md = "---\ntitle: My Doc\ncategory: guides\n---\n# Title\n\nContent"
        meta, body = parse_frontmatter(md)
        assert meta["title"] == "My Doc"
        assert meta["category"] == "guides"
        assert body.startswith("# Title")

    def test_quoted_values(self):
        md = '---\ntitle: "Quoted Title"\ncategory: \'single\'\n---\nBody'
        meta, body = parse_frontmatter(md)
        assert meta["title"] == "Quoted Title"
        assert meta["category"] == "single"

    def test_incomplete_frontmatter(self):
        md = "---\ntitle: Broken"
        meta, body = parse_frontmatter(md)
        assert meta == {}
        assert body == md

    def test_empty_frontmatter(self):
        md = "---\n---\nBody"
        meta, body = parse_frontmatter(md)
        assert meta == {}
        assert body == "Body"


# ---------------------------------------------------------------------------
# extract_title
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_h1(self):
        assert extract_title("# My Title\n\nContent") == "My Title"

    def test_no_h1(self):
        assert extract_title("No heading here") is None

    def test_h2_not_h1(self):
        assert extract_title("## Not H1") is None

    def test_h1_after_content(self):
        assert extract_title("Some text\n\n# Late Title") == "Late Title"


# ---------------------------------------------------------------------------
# chunk_by_headings
# ---------------------------------------------------------------------------


class TestChunkByHeadings:
    def test_no_h2(self):
        md = "# Title\n\nJust some content without H2 headers."
        chunks = chunk_by_headings(md, "test.md")
        assert len(chunks) == 1
        assert chunks[0]["title"] == "Title"

    def test_single_h2(self):
        md = "# Doc\n\nIntro\n\n## Section One\n\nContent of section one."
        chunks = chunk_by_headings(md, "test.md")
        assert len(chunks) == 1
        assert chunks[0]["title"] == "Section One"
        assert "Content of section one" in chunks[0]["content"]

    def test_multiple_h2(self):
        md = "# Doc\n\n## First\n\nFirst content.\n\n## Second\n\nSecond content."
        chunks = chunk_by_headings(md, "test.md")
        assert len(chunks) == 2
        assert chunks[0]["title"] == "First"
        assert chunks[1]["title"] == "Second"

    def test_section_path(self):
        md = "# My Doc\n\n## Setup\n\nSetup instructions."
        chunks = chunk_by_headings(md, "test.md")
        assert chunks[0]["section_path"] == "My Doc > Setup"

    def test_no_h1_uses_filename(self):
        md = "## Section\n\nContent here that is long enough."
        chunks = chunk_by_headings(md, "path/to/my-guide.md")
        assert chunks[0]["section_path"] == "my-guide > Section"

    def test_skips_tiny_sections(self):
        md = "# Doc\n\n## Empty\n\n## Real\n\nThis section has real content."
        chunks = chunk_by_headings(md, "test.md")
        # "## Empty" section is <20 chars, should be skipped
        assert all(c["title"] != "Empty" for c in chunks)

    def test_preserves_content(self):
        md = "# Doc\n\n## Code Example\n\n```python\ndef hello():\n    pass\n```\n\nMore text."
        chunks = chunk_by_headings(md, "test.md")
        assert "```python" in chunks[0]["content"]


# ---------------------------------------------------------------------------
# scan_files
# ---------------------------------------------------------------------------


class TestScanFiles:
    def test_single_file(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Test")
        assert scan_files(f) == [f]

    def test_directory(self, tmp_path):
        (tmp_path / "a.md").write_text("# A")
        (tmp_path / "b.md").write_text("# B")
        (tmp_path / "ignore.txt").write_text("not markdown")
        results = scan_files(tmp_path)
        assert len(results) == 2
        assert all(f.suffix == ".md" for f in results)

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.md").write_text("# Root")
        (sub / "nested.md").write_text("# Nested")
        results = scan_files(tmp_path)
        assert len(results) == 2

    def test_sorted(self, tmp_path):
        (tmp_path / "z.md").write_text("Z")
        (tmp_path / "a.md").write_text("A")
        results = scan_files(tmp_path)
        assert results[0].name == "a.md"

    def test_empty_dir(self, tmp_path):
        assert scan_files(tmp_path) == []

    def test_nonexistent(self, tmp_path):
        fake = tmp_path / "nope"
        # scan_files on a nonexistent path returns empty (Path.rglob on nonexistent)
        assert scan_files(fake) == []
