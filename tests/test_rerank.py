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


def test_default_model_matches_config_default(monkeypatch):
    """`rerank_model` must name the same real repo as `rerank.DEFAULT_MODEL`.

    Regression: `GnosisMcpConfig.rerank_model` defaulted to
    `onnx-community/ms-marco-MiniLM-L6-v2-ONNX`, which HuggingFace answers 401
    for at every path — the repo does not exist — while `rerank.py` named the
    real cross-encoder. `RERANK_ENABLED=true` could therefore never rerank: every
    search logged a rerank failure and returned unranked results.
    """
    from gnosis_mcp import rerank as rr
    from gnosis_mcp.config import GnosisMcpConfig

    monkeypatch.delenv("GNOSIS_MCP_RERANK_MODEL", raising=False)
    assert rr.DEFAULT_MODEL == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert GnosisMcpConfig().rerank_model == rr.DEFAULT_MODEL
    assert GnosisMcpConfig.from_env().rerank_model == rr.DEFAULT_MODEL


def test_rerank_keeps_original_score_alongside_rerank_score(monkeypatch):
    """`rerank` adds `rerank_score`; the backend's `score` stays untouched."""
    from gnosis_mcp import rerank as rr

    class FakeReranker(rr.Reranker):
        def _ensure_model(self) -> None:
            pass

        def score(self, query: str, passages: list[str]) -> list[float]:
            return [float(len(p)) for p in passages]

    results = [
        {"file_path": "a.md", "content": "short", "score": 0.9},
        {"file_path": "b.md", "content": "a much longer passage", "score": 0.1},
    ]
    ranked = FakeReranker().rerank("q", results, text_key="content")

    assert [r["file_path"] for r in ranked] == ["b.md", "a.md"]
    assert all("rerank_score" in r for r in ranked)
    assert [r["score"] for r in ranked] == [0.1, 0.9], "backend score must be preserved"


def test_unavailable_model_error_is_actionable(monkeypatch, tmp_path):
    """A dead model must name itself, the HTTP status, and both fixes."""
    import urllib.error

    from gnosis_mcp import rerank as rr

    def _boom(url, filename):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(rr.urllib.request, "urlretrieve", _boom)

    with pytest.raises(RuntimeError) as exc:
        rr._download_model("onnx-community/ms-marco-MiniLM-L6-v2-ONNX", tmp_path)

    message = str(exc.value)
    assert "onnx-community/ms-marco-MiniLM-L6-v2-ONNX" in message
    assert "HTTP 401" in message
    assert "GNOSIS_MCP_RERANK_MODEL" in message
    assert "GNOSIS_MCP_RERANK_ENABLED=false" in message
    assert rr.DEFAULT_MODEL in message


def test_check_model_available_reports_http_status(monkeypatch, tmp_path):
    import urllib.error

    from gnosis_mcp import rerank as rr

    def _boom(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(rr.urllib.request, "urlopen", _boom)

    available, detail = rr.check_model_available("org/missing", cache_dir=tmp_path / "cache")
    assert available is False
    assert "HTTP 401" in detail


def test_check_model_available_skips_network_for_cached_model(monkeypatch, tmp_path):
    from gnosis_mcp import rerank as rr

    cache = tmp_path / "cache"
    model_dir = cache / "org--model"
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "tokenizer.json").write_text("{}")
    (model_dir / "onnx" / "model.onnx").write_bytes(b"onnx")

    def _unexpected(*args, **kwargs):  # pragma: no cover — must not be reached
        raise AssertionError("a cached model must not be probed over the network")

    monkeypatch.setattr(rr.urllib.request, "urlopen", _unexpected)

    assert rr.model_is_cached("org/model", cache) is True
    assert rr.check_model_available("org/model", cache_dir=cache) == (True, "cached")


def test_model_is_cached_needs_tokenizer_and_onnx(tmp_path):
    from gnosis_mcp import rerank as rr

    cache = tmp_path / "cache"
    model_dir = cache / "org--model"
    model_dir.mkdir(parents=True)
    (model_dir / "tokenizer.json").write_text("{}")
    assert rr.model_is_cached("org/model", cache) is False, "weights are still missing"

    (model_dir / "model.onnx").write_bytes(b"onnx")  # top-level layout
    assert rr.model_is_cached("org/model", cache) is True


def test_rerank_score_survives_server_result_formatting():
    """`rerank.py` writes `rerank_score`; `_format_search_result` must not drop it.

    Without the passthrough a reranked result set ships retrieval scores that
    disagree with the order the caller is reading (0.3493 shown above 0.3976).
    """
    from gnosis_mcp.server import _format_search_result

    row = {
        "file_path": "a.md",
        "title": "A",
        "content": "some content",
        "score": 0.3493,
        "rerank_score": 0.9123,
    }

    assert _format_search_result(row, 200)["rerank_score"] == 0.9123


@pytest.mark.e2e
def test_default_model_is_fetchable_and_reranks():
    """The shipped default must resolve on HuggingFace and score pairs for real.

    Skips (rather than fails) when the model is neither cached nor reachable, so
    an offline checkout stays green; CI excludes the `e2e` mark anyway.
    """
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    from gnosis_mcp import rerank as rr

    available, detail = rr.check_model_available(rr.DEFAULT_MODEL, timeout=10)
    if not available:
        pytest.skip(f"reranker model {rr.DEFAULT_MODEL} not reachable: {detail}")

    reranker = rr.Reranker(model_id=rr.DEFAULT_MODEL)
    results = [
        {"file_path": "widgets.md", "content": "Widgets are pipeline stages for documentation."},
        {"file_path": "bananas.md", "content": "Bananas are a yellow tropical fruit."},
    ]
    ranked = reranker.rerank("what is a widget", results)

    assert ranked[0]["file_path"] == "widgets.md"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]


def test_rerank_score_precision_keeps_saturated_scores_distinct(monkeypatch):
    """Sigmoid-saturated pairs must not both display as 0.0.

    The ranking comes from the raw logits, so the score a client is shown has to
    preserve that ordering. Rounding to 4 decimal places collapsed logits of
    -11.20 and -11.28 to the same 0.0, which reads as a tie in an order the
    reranker actually decided.
    """
    from gnosis_mcp import rerank as rr

    logits = {"a.md": -11.2, "b.md": -11.28, "c.md": 4.0}

    class FakeReranker(rr.Reranker):
        def score(self, query: str, passages: list[str]) -> list[float]:
            import math

            return [1.0 / (1.0 + math.exp(-logits[p])) for p in passages]

    results = [{"file_path": path, "content": path} for path in logits]
    ranked = FakeReranker().rerank("q", results, text_key="content")

    assert [r["file_path"] for r in ranked] == ["c.md", "a.md", "b.md"]
    scores = [r["rerank_score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert scores[1] > scores[2], f"saturated scores collapsed to a tie: {scores}"
