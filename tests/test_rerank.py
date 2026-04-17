"""Unit tests for the opt-in cross-encoder reranker.

Heavy model download is intentionally avoided — these tests cover the pure
ranking logic and the ImportError-friendly behaviour. Real model integration
is exercised indirectly by the benchmark scripts.
"""

from __future__ import annotations

import pytest


def test_rerank_reorders_by_score(monkeypatch):
    from gnosis_mcp import rerank as rr

    class FakeReranker(rr.Reranker):
        def _ensure_model(self) -> None:  # noqa: D401
            """Bypass model download in tests."""
            pass

        def score(self, query: str, passages: list[str]) -> list[float]:
            # Score by passage length — longer first, as a deterministic stand-in
            return [float(len(p)) for p in passages]

    reranker = FakeReranker()
    results = [
        {"file_path": "a.md", "content": "short"},
        {"file_path": "b.md", "content": "medium text"},
        {"file_path": "c.md", "content": "a much longer passage with many words"},
    ]
    ranked = reranker.rerank("query", results, text_key="content")
    assert [r["file_path"] for r in ranked] == ["c.md", "b.md", "a.md"]
    assert "rerank_score" in ranked[0]
    assert ranked[0]["rerank_score"] >= ranked[-1]["rerank_score"]


def test_rerank_empty_input():
    from gnosis_mcp.rerank import Reranker

    assert Reranker().rerank("q", []) == []


def test_rerank_respects_top_k(monkeypatch):
    from gnosis_mcp import rerank as rr

    class FakeReranker(rr.Reranker):
        def _ensure_model(self) -> None:
            pass

        def score(self, query: str, passages: list[str]) -> list[float]:
            return [float(len(p)) for p in passages]

    reranker = FakeReranker()
    results = [{"file_path": f"doc{i}.md", "content": "x" * (i + 1)} for i in range(5)]
    ranked = reranker.rerank("q", results, text_key="content", top_k=2)
    assert len(ranked) == 2
    # Longest two passages should survive (doc5 and doc4)
    assert {r["file_path"] for r in ranked} == {"doc4.md", "doc3.md"}


def test_reject_non_huggingface_url(monkeypatch, tmp_path):
    from gnosis_mcp import rerank as rr

    # Pretend the default model_id is attacker-controlled pointing off-HF.
    monkeypatch.setattr(rr, "_HF_BASE", "https://evil.example")
    with pytest.raises(RuntimeError, match="non-HuggingFace"):
        rr._download_model("org/model", tmp_path)
