"""Search quality eval harness — measures Precision@K, MRR, and Hit Rate.

Uses query-answer pairs from cases.json to score retrieval quality.
Runs against a real SQLite backend populated with test documents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.ingest import chunk_by_headings

if TYPE_CHECKING:
    from gnosis_mcp.sqlite_backend import SqliteBackend

log = logging.getLogger("gnosis_mcp.eval")

CASES_PATH = Path(__file__).parent / "cases.json"
K = 5  # Precision@K, Hit Rate@K


@dataclass
class EvalResult:
    """Result of evaluating a single query."""

    query: str
    expected_paths: list[str]
    returned_paths: list[str]
    precision_at_k: float
    reciprocal_rank: float
    hit: bool
    description: str = ""


@dataclass
class EvalSummary:
    """Aggregate metrics across all eval cases."""

    results: list[EvalResult] = field(default_factory=list)

    @property
    def mean_precision(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.precision_at_k for r in self.results) / len(self.results)

    @property
    def mrr(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.reciprocal_rank for r in self.results) / len(self.results)

    @property
    def hit_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.hit) / len(self.results)


def _is_relevant(returned_path: str, expected_patterns: list[str]) -> bool:
    """Check if a returned path matches any expected pattern (substring match)."""
    for pattern in expected_patterns:
        if pattern.lower() in returned_path.lower():
            return True
    return False


def _score_query(
    query: str,
    expected_paths: list[str],
    returned_paths: list[str],
    description: str = "",
) -> EvalResult:
    """Score a single query result."""
    relevant_count = 0
    first_relevant_rank = 0

    for i, path in enumerate(returned_paths[:K], 1):
        if _is_relevant(path, expected_paths):
            relevant_count += 1
            if first_relevant_rank == 0:
                first_relevant_rank = i

    result_count = min(K, len(returned_paths)) if returned_paths else 1
    precision = relevant_count / result_count
    rr = 1.0 / first_relevant_rank if first_relevant_rank > 0 else 0.0
    hit = first_relevant_rank > 0

    return EvalResult(
        query=query,
        expected_paths=expected_paths,
        returned_paths=returned_paths[:K],
        precision_at_k=precision,
        reciprocal_rank=rr,
        hit=hit,
        description=description,
    )


# ---------------------------------------------------------------------------
# Test fixture: populate a SQLite DB with sample docs
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    {
        "path": "guides/quickstart.md",
        "content": "# Quick Start Guide\n\nHow to install and set up gnosis-mcp.\n\n## Installation\n\npip install gnosis-mcp\n\n## Configuration\n\nSet environment variables for your backend.",
        "title": "Quick Start Guide",
        "category": "guides",
    },
    {
        "path": "guides/configuration.md",
        "content": "# Configuration\n\nAll settings via environment variables.\n\n## Database Config\n\nGNOSIS_MCP_DATABASE_URL for PostgreSQL.\n\n## Webhook Config\n\nGNOSIS_MCP_WEBHOOK_URL to receive notifications on doc changes.",
        "title": "Configuration",
        "category": "guides",
    },
    {
        "path": "architecture/backend.md",
        "content": "# Backend Architecture\n\nTwo backends: SQLite (default) and PostgreSQL.\n\n## PostgreSQL Backend\n\nUses asyncpg with tsvector for full-text search.\n\n## SQLite Backend\n\nUses aiosqlite with FTS5 and porter stemmer.",
        "title": "Backend Architecture",
        "category": "architecture",
    },
    {
        "path": "guides/search.md",
        "content": "# Search Documentation\n\nSearch your docs with keyword or hybrid search.\n\n## Keyword Search\n\nFTS5 on SQLite, tsvector on PostgreSQL.\n\n## Hybrid Search\n\nCombine keyword + semantic with RRF fusion.",
        "title": "Search Documentation",
        "category": "guides",
    },
    {
        "path": "guides/webhooks.md",
        "content": "# Webhook Notifications\n\nReceive HTTP POST notifications when documents change.\n\n## Setup\n\nSet GNOSIS_MCP_WEBHOOK_URL. Fire-and-forget POST on upsert/delete.\n\n## Payload\n\nJSON with action, path, timestamp fields.",
        "title": "Webhook Notifications",
        "category": "guides",
    },
]

SAMPLE_GIT_HISTORY_DOCS = [
    {
        "path": "git-history/src/auth.py",
        "content": (
            "# Git History: src/auth.py\n\n"
            "## 2026-02-18\n\n"
            "Author: Alice <alice@example.com>\n\n"
            "Refactored authentication module to use JWT tokens\n\n"
            "Files: src/auth.py\n\n"
            "## 2026-02-15\n\n"
            "Author: Bob <bob@example.com>\n\n"
            "Initial authentication with session cookies\n\n"
            "Files: src/auth.py"
        ),
        "title": "Git history for src/auth.py",
        "category": "git-history",
    },
    {
        "path": "git-history/src/db.py",
        "content": (
            "# Git History: src/db.py\n\n"
            "## 2026-02-20\n\n"
            "Author: Alice <alice@example.com>\n\n"
            "Fixed database connection pool exhaustion under high load\n\n"
            "Files: src/db.py\n\n"
            "## 2026-02-10\n\n"
            "Author: Charlie <charlie@example.com>\n\n"
            "Added connection pooling with asyncpg\n\n"
            "Files: src/db.py"
        ),
        "title": "Git history for src/db.py",
        "category": "git-history",
    },
    {
        "path": "git-history/tests/test_search.py",
        "content": (
            "# Git History: tests/test_search.py\n\n"
            "## 2026-02-19\n\n"
            "Author: Bob <bob@example.com>\n\n"
            "Added unit tests for search ranking and hybrid mode\n\n"
            "Files: tests/test_search.py"
        ),
        "title": "Git history for tests/test_search.py",
        "category": "git-history",
    },
    {
        "path": "git-history/pyproject.toml",
        "content": (
            "# Git History: pyproject.toml\n\n"
            "## 2026-02-21\n\n"
            "Author: Alice <alice@example.com>\n\n"
            "Bumped version to 2.0 for major release\n\n"
            "Files: pyproject.toml\n\n"
            "## 2026-02-14\n\n"
            "Author: Alice <alice@example.com>\n\n"
            "Initial project setup with hatchling build system\n\n"
            "Files: pyproject.toml"
        ),
        "title": "Git history for pyproject.toml",
        "category": "git-history",
    },
]


async def _build_eval_db(tmp_path: Path) -> "SqliteBackend":
    """Create a populated SQLite backend for eval testing."""
    from gnosis_mcp.sqlite_backend import SqliteBackend

    db_path = tmp_path / "eval.db"
    cfg = GnosisMcpConfig(database_url=str(db_path))
    backend = SqliteBackend(cfg)
    await backend.startup()
    await backend.init_schema()

    for doc in SAMPLE_DOCS + SAMPLE_GIT_HISTORY_DOCS:
        chunks = chunk_by_headings(doc["content"], doc["path"])
        await backend.ingest_file(
            doc["path"],
            chunks,
            title=doc["title"],
            category=doc["category"],
            audience="all",
            tags=None,
            content_hash=None,
            has_tags_col=True,
            has_hash_col=True,
        )

    return backend


def _load_cases() -> list[dict]:
    """Load eval cases from JSON file."""
    return json.loads(CASES_PATH.read_text())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEvalHarness:
    """Search quality evaluation tests."""

    @pytest.fixture(autouse=True)
    def setup_backend(self, tmp_path):
        self.backend = asyncio.run(_build_eval_db(tmp_path))
        yield
        asyncio.run(self.backend.shutdown())

    def _search(self, query: str, category: str | None = None) -> list[str]:
        results = asyncio.run(self.backend.search(query, category=category, limit=K))
        return [r["file_path"] for r in results]

    def test_eval_cases(self):
        """Run all eval cases and report aggregate metrics."""
        cases = _load_cases()
        summary = EvalSummary()

        for case in cases:
            returned = self._search(case["query"], case.get("category"))
            result = _score_query(
                query=case["query"],
                expected_paths=case["expected_paths"],
                returned_paths=returned,
                description=case.get("description", ""),
            )
            summary.results.append(result)

        # Report
        print(f"\n{'=' * 60}")
        print(f"Search Quality Eval — {len(summary.results)} cases")
        print(f"{'=' * 60}")
        for r in summary.results:
            status = "PASS" if r.hit else "MISS"
            print(
                f"  [{status}] {r.query!r:40s} "
                f"P@{K}={r.precision_at_k:.2f} RR={r.reciprocal_rank:.2f} "
                f"got={r.returned_paths}"
            )
        print(f"{'=' * 60}")
        print(f"  Mean Precision@{K}: {summary.mean_precision:.3f}")
        print(f"  MRR:                {summary.mrr:.3f}")
        print(f"  Hit Rate@{K}:       {summary.hit_rate:.3f}")
        print(f"{'=' * 60}")

        # Thresholds — adjust as search improves
        assert summary.hit_rate >= 0.6, f"Hit rate {summary.hit_rate:.2f} below threshold 0.60"

    def test_individual_search_docs(self):
        """Each sample doc should be findable by a distinctive keyword."""
        # Use distinctive terms rather than generic titles (FTS5 needs matching tokens)
        queries = {
            "guides/quickstart.md": "quickstart install",
            "guides/configuration.md": "GNOSIS_MCP_DATABASE_URL",
            "architecture/backend.md": "backend architecture",
            "guides/search.md": "keyword hybrid search",
            "guides/webhooks.md": "webhook notification",
        }
        for doc in SAMPLE_DOCS:
            query = queries[doc["path"]]
            results = self._search(query)
            assert doc["path"] in results, (
                f"Expected {doc['path']} in results for query {query!r}, got {results}"
            )

    def test_category_filter(self):
        """Category filter should only return docs from that category."""
        results = asyncio.run(self.backend.search("search", category="architecture", limit=K))
        for r in results:
            assert r["category"] == "architecture"

    def test_precision_helper(self):
        """Test the _score_query helper directly."""
        result = _score_query(
            query="test",
            expected_paths=["guides/"],
            returned_paths=[
                "guides/quickstart.md",
                "architecture/backend.md",
                "guides/search.md",
            ],
        )
        assert result.precision_at_k == pytest.approx(2 / 3)
        assert result.reciprocal_rank == pytest.approx(1.0)
        assert result.hit is True

    def test_miss_scoring(self):
        """Test scoring when nothing matches."""
        result = _score_query(
            query="test",
            expected_paths=["nonexistent/"],
            returned_paths=["guides/quickstart.md"],
        )
        assert result.precision_at_k == 0.0
        assert result.reciprocal_rank == 0.0
        assert result.hit is False
