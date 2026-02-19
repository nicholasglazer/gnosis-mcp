"""Tests for Reciprocal Rank Fusion algorithm used in SQLite hybrid search."""

import pytest

from gnosis_mcp.sqlite_backend import _RRF_K


class TestRRFConstant:
    def test_rrf_k_is_60(self):
        assert _RRF_K == 60


class TestRRFScoring:
    """Test the RRF scoring logic directly (extracted from _search_hybrid)."""

    def _compute_rrf(
        self, keyword_ranks: dict[str, int], semantic_ranks: dict[str, int]
    ) -> list[tuple[float, str]]:
        """Standalone RRF computation matching _search_hybrid logic."""
        all_keys = set(keyword_ranks) | set(semantic_ranks)
        scores = []
        for key in all_keys:
            score = 0.0
            if key in keyword_ranks:
                score += 1.0 / (_RRF_K + keyword_ranks[key])
            if key in semantic_ranks:
                score += 1.0 / (_RRF_K + semantic_ranks[key])
            scores.append((score, key))
        scores.sort(reverse=True)
        return scores

    def test_single_keyword_result(self):
        scores = self._compute_rrf({"doc_a": 1}, {})
        assert len(scores) == 1
        assert scores[0][1] == "doc_a"
        assert scores[0][0] == pytest.approx(1.0 / 61)

    def test_single_semantic_result(self):
        scores = self._compute_rrf({}, {"doc_a": 1})
        assert len(scores) == 1
        assert scores[0][1] == "doc_a"
        assert scores[0][0] == pytest.approx(1.0 / 61)

    def test_overlapping_results_score_higher(self):
        """Documents appearing in both keyword and semantic results should rank higher."""
        scores = self._compute_rrf(
            {"both": 1, "keyword_only": 2},
            {"both": 1, "semantic_only": 2},
        )
        score_map = {key: score for score, key in scores}
        assert score_map["both"] > score_map["keyword_only"]
        assert score_map["both"] > score_map["semantic_only"]

    def test_overlapping_result_double_score(self):
        """Rank-1 in both lists should give exactly 2/(k+1)."""
        scores = self._compute_rrf({"doc": 1}, {"doc": 1})
        expected = 2.0 / (_RRF_K + 1)
        assert scores[0][0] == pytest.approx(expected)

    def test_ordering_respects_ranks(self):
        """Lower rank (better position) should produce higher RRF score."""
        scores = self._compute_rrf(
            {"rank1": 1, "rank5": 5, "rank10": 10},
            {},
        )
        assert scores[0][1] == "rank1"
        assert scores[1][1] == "rank5"
        assert scores[2][1] == "rank10"

    def test_empty_inputs(self):
        scores = self._compute_rrf({}, {})
        assert scores == []

    def test_many_results_merge(self):
        """RRF correctly merges disjoint result sets."""
        keyword = {f"kw_{i}": i for i in range(1, 11)}
        semantic = {f"sem_{i}": i for i in range(1, 11)}
        scores = self._compute_rrf(keyword, semantic)
        assert len(scores) == 20  # all unique

    def test_tie_breaking_deterministic(self):
        """Results with identical scores should still produce a valid ordering."""
        # Two docs at rank 1 in different lists → same RRF score
        scores = self._compute_rrf({"a": 1}, {"b": 1})
        assert len(scores) == 2
        assert scores[0][0] == scores[1][0]  # Same score
