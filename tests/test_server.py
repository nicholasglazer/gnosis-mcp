"""Tests for server helpers (no DB required)."""

from stele.server import _split_chunks


class TestSplitChunks:
    def test_short_content_single_chunk(self):
        result = _split_chunks("Hello world", max_size=100)
        assert result == ["Hello world"]

    def test_splits_at_paragraph_boundary(self):
        content = "A" * 50 + "\n\n" + "B" * 50
        result = _split_chunks(content, max_size=60)
        assert len(result) == 2
        assert result[0] == "A" * 50
        assert result[1] == "B" * 50

    def test_multiple_chunks(self):
        paragraphs = ["Para " + str(i) + " " + "x" * 40 for i in range(10)]
        content = "\n\n".join(paragraphs)
        result = _split_chunks(content, max_size=100)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 120  # some tolerance for boundary

    def test_empty_content(self):
        result = _split_chunks("", max_size=100)
        assert result == [""]

    def test_exact_boundary(self):
        content = "A" * 4000
        result = _split_chunks(content, max_size=4000)
        assert result == [content]

    def test_no_paragraph_breaks(self):
        content = "A" * 5000
        result = _split_chunks(content, max_size=4000)
        # No paragraph breaks means it falls through to single chunk
        assert len(result) == 1
        assert result[0] == content
