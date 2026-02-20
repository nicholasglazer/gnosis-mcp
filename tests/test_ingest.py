"""Tests for gnosis_mcp.ingest — file scanning, frontmatter, chunking."""

from pathlib import Path

import pytest

from gnosis_mcp.ingest import (
    _convert_csv,
    _convert_ipynb,
    _convert_json,
    _convert_to_markdown,
    _convert_toml,
    _convert_txt,
    _find_protected_ranges,
    _split_paragraphs_safe,
    chunk_by_headings,
    content_hash,
    extract_relates_to,
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
# extract_relates_to
# ---------------------------------------------------------------------------


class TestExtractRelatesTo:
    def test_no_frontmatter(self):
        assert extract_relates_to("# Title\n\nContent") == []

    def test_no_relates_to(self):
        md = "---\ntitle: My Doc\ncategory: guides\n---\n# Title"
        assert extract_relates_to(md) == []

    def test_comma_separated(self):
        md = "---\nrelates_to: guides/setup.md, architecture/overview.md\n---\nBody"
        result = extract_relates_to(md)
        assert result == ["guides/setup.md", "architecture/overview.md"]

    def test_single_value(self):
        md = "---\nrelates_to: guides/setup.md\n---\nBody"
        result = extract_relates_to(md)
        assert result == ["guides/setup.md"]

    def test_yaml_list(self):
        md = "---\nrelates_to:\n  - guides/setup.md\n  - architecture/overview.md\n---\nBody"
        result = extract_relates_to(md)
        assert result == ["guides/setup.md", "architecture/overview.md"]

    def test_filters_globs(self):
        md = "---\nrelates_to:\n  - guides/*.md\n  - architecture/overview.md\n  - src/**/*.ts\n---\nBody"
        result = extract_relates_to(md)
        assert result == ["architecture/overview.md"]

    def test_quoted_values(self):
        md = '---\nrelates_to: "guides/setup.md", \'architecture/overview.md\'\n---\nBody'
        result = extract_relates_to(md)
        assert result == ["guides/setup.md", "architecture/overview.md"]

    def test_yaml_list_with_other_fields(self):
        md = "---\ntitle: Test\nrelates_to:\n  - guides/a.md\n  - guides/b.md\ncategory: guides\n---\nBody"
        result = extract_relates_to(md)
        assert result == ["guides/a.md", "guides/b.md"]

    def test_incomplete_frontmatter(self):
        md = "---\nrelates_to: foo.md"
        assert extract_relates_to(md) == []

    def test_empty_relates_to(self):
        md = "---\nrelates_to:\n---\nBody"
        assert extract_relates_to(md) == []


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

    def test_oversized_h2_splits_by_h3(self):
        """An oversized H2 section should split at H3 boundaries."""
        h3a = "### Sub A\n\n" + "A " * 100
        h3b = "### Sub B\n\n" + "B " * 100
        md = f"# Doc\n\n## Big Section\n\n{h3a}\n\n{h3b}"
        chunks = chunk_by_headings(md, "test.md", max_chunk_size=300)
        assert len(chunks) >= 2
        assert any("Sub A" in c["title"] for c in chunks)
        assert any("Sub B" in c["title"] for c in chunks)

    def test_oversized_no_headings_splits_paragraphs(self):
        """Large doc with no headings should split at paragraph boundaries."""
        paras = ["Paragraph " + str(i) + " " + "x" * 80 for i in range(10)]
        md = "\n\n".join(paras)
        chunks = chunk_by_headings(md, "test.md", max_chunk_size=200)
        assert len(chunks) > 1
        # All content should be preserved
        rejoined = "\n\n".join(c["content"] for c in chunks)
        for i in range(10):
            assert f"Paragraph {i}" in rejoined

    def test_code_block_not_split(self):
        """Code blocks should never be split across chunks."""
        code = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(30)) + "\n```"
        md = f"# Doc\n\n## Section\n\nBefore code.\n\n{code}\n\nAfter code."
        chunks = chunk_by_headings(md, "test.md", max_chunk_size=200)
        # Find the chunk(s) containing the code block
        code_chunks = [c for c in chunks if "```python" in c["content"]]
        assert len(code_chunks) >= 1
        for cc in code_chunks:
            # Code block must be complete (has opening AND closing)
            if "```python" in cc["content"]:
                assert cc["content"].count("```") >= 2

    def test_table_not_split(self):
        """Tables should never be split across chunks."""
        rows = "\n".join(f"| col{i}a | col{i}b |" for i in range(20))
        table = f"| Header A | Header B |\n| --- | --- |\n{rows}"
        md = f"# Doc\n\nBefore table.\n\n{table}\n\nAfter table."
        chunks = chunk_by_headings(md, "test.md", max_chunk_size=200)
        table_chunks = [c for c in chunks if "Header A" in c["content"]]
        assert len(table_chunks) >= 1
        # Table header and last row should be in the same chunk
        for tc in table_chunks:
            if "Header A" in tc["content"]:
                assert "col19a" in tc["content"]

    def test_h4_split_for_deeply_nested(self):
        """H4 should be used as a split point for oversized H3 sections."""
        h4a = "#### Detail A\n\n" + "A " * 100
        h4b = "#### Detail B\n\n" + "B " * 100
        h3 = f"### Subsection\n\n{h4a}\n\n{h4b}"
        md = f"# Doc\n\n## Section\n\n{h3}"
        chunks = chunk_by_headings(md, "test.md", max_chunk_size=250)
        assert len(chunks) >= 2
        assert any("Detail A" in c["title"] for c in chunks)
        assert any("Detail B" in c["title"] for c in chunks)

    def test_cont_suffix_on_paragraph_splits(self):
        """Paragraph-split chunks get (cont.) suffix."""
        md = "# Doc\n\n" + "\n\n".join(f"Para {i} " + "x" * 80 for i in range(10))
        chunks = chunk_by_headings(md, "test.md", max_chunk_size=200)
        if len(chunks) > 1:
            assert any("(cont.)" in c["title"] for c in chunks[1:])

    def test_max_chunk_size_default(self):
        """Default max_chunk_size is 4000."""
        md = "# Doc\n\n## Section\n\n" + "x " * 1500
        chunks = chunk_by_headings(md, "test.md")
        assert len(chunks) == 1  # 3000 chars < 4000 default


# ---------------------------------------------------------------------------
# Protected ranges and safe splitting
# ---------------------------------------------------------------------------


class TestProtectedRanges:
    def test_fenced_code_block(self):
        text = "Before\n\n```python\ncode here\n```\n\nAfter"
        ranges = _find_protected_ranges(text)
        assert len(ranges) >= 1
        # The code block range should contain "code here"
        code_range = ranges[0]
        assert "code here" in text[code_range[0]:code_range[1]]

    def test_tilde_fence(self):
        text = "Before\n\n~~~\ncode\n~~~\n\nAfter"
        ranges = _find_protected_ranges(text)
        assert len(ranges) >= 1

    def test_unclosed_fence(self):
        text = "Before\n\n```python\nunclosed code"
        ranges = _find_protected_ranges(text)
        assert len(ranges) == 1
        assert ranges[0][1] == len(text)

    def test_table_detection(self):
        text = "Before\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nAfter"
        ranges = _find_protected_ranges(text)
        table_ranges = [r for r in ranges if "| A |" in text[r[0]:r[1]]]
        assert len(table_ranges) == 1

    def test_no_protected(self):
        text = "Just plain text\n\nWith paragraphs"
        assert _find_protected_ranges(text) == []


class TestSplitParagraphsSafe:
    def test_short_text(self):
        assert _split_paragraphs_safe("short", 100) == ["short"]

    def test_splits_at_paragraph(self):
        text = "A" * 50 + "\n\n" + "B" * 50
        result = _split_paragraphs_safe(text, 60)
        assert len(result) == 2

    def test_preserves_code_blocks(self):
        code = "```\n" + "x\n" * 40 + "```"
        text = "Before\n\n" + code + "\n\nAfter"
        result = _split_paragraphs_safe(text, 50)
        # Code block should be in one chunk
        code_chunks = [c for c in result if "```" in c]
        for cc in code_chunks:
            assert cc.count("```") >= 2 or cc.endswith("```")

    def test_no_split_points(self):
        text = "A" * 200
        result = _split_paragraphs_safe(text, 100)
        assert result == [text]

    def test_multiple_splits(self):
        parts = [f"P{i} " + "x" * 30 for i in range(5)]
        text = "\n\n".join(parts)
        result = _split_paragraphs_safe(text, 50)
        assert len(result) >= 3


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
        (tmp_path / "c.txt").write_text("plain text")
        (tmp_path / "ignore.py").write_text("# not docs")
        results = scan_files(tmp_path)
        assert len(results) == 3  # .md + .txt are supported
        assert {f.suffix for f in results} == {".md", ".txt"}
        assert not any(f.suffix == ".py" for f in results)

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

    def test_finds_all_supported_extensions(self, tmp_path):
        for ext in (".md", ".txt", ".ipynb", ".toml", ".csv", ".json"):
            (tmp_path / f"doc{ext}").write_text("content")
        (tmp_path / "skip.py").write_text("python")
        (tmp_path / "skip.html").write_text("<p>html</p>")
        results = scan_files(tmp_path)
        exts = {f.suffix for f in results}
        assert exts == {".md", ".txt", ".ipynb", ".toml", ".csv", ".json"}


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


class TestConvertTxt:
    def test_adds_title(self):
        result = _convert_txt("Hello world", Path("my-notes.txt"))
        assert result.startswith("# My Notes\n\n")
        assert "Hello world" in result

    def test_title_from_underscores(self):
        result = _convert_txt("content", Path("api_reference.txt"))
        assert "# Api Reference" in result


class TestConvertIpynb:
    def test_basic_notebook(self):
        import json
        nb = {
            "metadata": {"kernelspec": {"language": "python"}},
            "nbformat": 4,
            "cells": [
                {"cell_type": "markdown", "source": ["# Title\n", "Some text"]},
                {"cell_type": "code", "source": ["print('hello')"], "outputs": []},
                {"cell_type": "markdown", "source": ["## Section 2"]},
            ],
        }
        result = _convert_ipynb(json.dumps(nb), Path("nb.ipynb"))
        assert "# Title" in result
        assert "```python\nprint('hello')\n```" in result
        assert "## Section 2" in result

    def test_empty_cells_skipped(self):
        import json
        nb = {
            "metadata": {},
            "cells": [
                {"cell_type": "code", "source": [], "outputs": []},
                {"cell_type": "markdown", "source": ["# Only this"]},
            ],
        }
        result = _convert_ipynb(json.dumps(nb), Path("nb.ipynb"))
        assert "# Only this" in result
        assert "```" not in result

    def test_invalid_json_passthrough(self):
        result = _convert_ipynb("not json{", Path("bad.ipynb"))
        assert result == "not json{"

    def test_source_as_string(self):
        import json
        nb = {
            "metadata": {},
            "cells": [{"cell_type": "markdown", "source": "# Hello"}],
        }
        result = _convert_ipynb(json.dumps(nb), Path("nb.ipynb"))
        assert "# Hello" in result


class TestConvertToml:
    def test_pyproject(self):
        toml = '[project]\nname = "foo"\nversion = "1.0"\n\n[tool.ruff]\nline-length = 99\n'
        result = _convert_toml(toml, Path("pyproject.toml"))
        assert "# pyproject.toml" in result
        assert "## project" in result
        assert "**name**" in result
        assert "## tool" in result

    def test_invalid_toml_fallback(self):
        result = _convert_toml("not valid [[[toml", Path("bad.toml"))
        assert "```toml" in result

    def test_top_level_scalars(self):
        result = _convert_toml('title = "My Config"\nversion = 2\n', Path("config.toml"))
        assert "**title**" in result
        assert "**version**" in result

    def test_list_values(self):
        toml = '[project]\nkeywords = ["a", "b", "c"]\n'
        result = _convert_toml(toml, Path("p.toml"))
        assert "keywords" in result
        assert '"a"' in result


class TestConvertCsv:
    def test_basic_csv(self):
        csv_text = "name,age,city\nAlice,30,NYC\nBob,25,LA\n"
        result = _convert_csv(csv_text, Path("people.csv"))
        assert "| name | age | city |" in result
        assert "| --- | --- | --- |" in result
        assert "| Alice | 30 | NYC |" in result
        assert "| Bob | 25 | LA |" in result

    def test_single_row_passthrough(self):
        result = _convert_csv("just,a,header\n", Path("empty.csv"))
        assert result == "just,a,header\n"

    def test_short_row_padded(self):
        csv_text = "a,b,c\n1\n"
        result = _convert_csv(csv_text, Path("short.csv"))
        assert "| 1 |  |  |" in result


class TestConvertJson:
    def test_dict_with_sections(self):
        import json
        data = {"name": "foo", "config": {"key": "val"}, "items": [1, 2, 3]}
        result = _convert_json(json.dumps(data), Path("data.json"))
        assert "## config" in result
        assert "## items" in result
        assert "**name**" in result

    def test_array_as_code_block(self):
        import json
        result = _convert_json(json.dumps([1, 2, 3]), Path("arr.json"))
        assert "```json" in result

    def test_invalid_json_passthrough(self):
        result = _convert_json("{bad json", Path("bad.json"))
        assert result == "{bad json"


class TestConvertToMarkdownDispatch:
    def test_md_passthrough(self):
        text = "# Hello\n\nWorld"
        assert _convert_to_markdown(text, Path("doc.md")) == text

    def test_txt_converts(self):
        result = _convert_to_markdown("hello", Path("readme.txt"))
        assert "# Readme" in result

    def test_unknown_ext_passthrough(self):
        text = "some content"
        assert _convert_to_markdown(text, Path("file.xyz")) == text


# ---------------------------------------------------------------------------
# chunk_size wiring (config.chunk_size → chunk_by_headings)
# ---------------------------------------------------------------------------


class TestChunkSizeWiring:
    def test_small_chunk_size_produces_more_chunks(self):
        """Tiny chunk_size should produce more chunks than the default."""
        md = "# Big\n\n## A\n\n" + "word " * 200 + "\n\n## B\n\n" + "word " * 200
        default = chunk_by_headings(md, "big.md")
        small = chunk_by_headings(md, "big.md", max_chunk_size=100)
        assert len(small) > len(default)

    def test_large_chunk_size_fewer_chunks(self):
        """Very large chunk_size should keep more content together."""
        md = "# Doc\n\n" + "\n\n".join(f"## S{i}\n\n" + "x " * 50 for i in range(5))
        normal = chunk_by_headings(md, "doc.md", max_chunk_size=200)
        large = chunk_by_headings(md, "doc.md", max_chunk_size=10000)
        assert len(large) <= len(normal)
