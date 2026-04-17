"""Tests for gnosis_mcp.parsers.git_history — pure functions + integration."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from gnosis_mcp.parsers.git_history import (
    GitCommit,
    GitIngestConfig,
    _build_cross_file_links,
    group_by_file,
    parse_git_log,
    render_history_markdown,
    should_include,
    _content_hash,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_LOG = """\
---GNOSIS_COMMIT---
HASH:abc123def456789
AUTHOR:Alice
EMAIL:alice@example.com
DATE:2026-02-20T10:30:00+01:00
SUBJECT:Add billing module
---GNOSIS_BODY_START---
Implemented charge-before-service pattern.
Closes #42.
---GNOSIS_BODY_END---
---GNOSIS_FILES---
src/billing.py
src/stripe.py
tests/test_billing.py

---GNOSIS_COMMIT---
HASH:def789abc012345
AUTHOR:Bob
EMAIL:bob@example.com
DATE:2026-02-18T14:00:00+01:00
SUBJECT:Fix webhook retry
---GNOSIS_BODY_START---
Added idempotency key.
---GNOSIS_BODY_END---
---GNOSIS_FILES---
src/stripe.py
"""


def _make_commits() -> list[GitCommit]:
    return parse_git_log(SAMPLE_LOG)


# ---------------------------------------------------------------------------
# parse_git_log
# ---------------------------------------------------------------------------


class TestParseGitLog:
    def test_parses_two_commits(self):
        commits = _make_commits()
        assert len(commits) == 2

    def test_first_commit_fields(self):
        c = _make_commits()[0]
        assert c.hash == "abc123def456789"
        assert c.author == "Alice"
        assert c.author_email == "alice@example.com"
        assert c.date == "2026-02-20T10:30:00+01:00"
        assert c.subject == "Add billing module"
        assert "charge-before-service" in c.body
        assert c.files == ["src/billing.py", "src/stripe.py", "tests/test_billing.py"]

    def test_second_commit_fields(self):
        c = _make_commits()[1]
        assert c.hash == "def789abc012345"
        assert c.author == "Bob"
        assert c.author_email == "bob@example.com"
        assert c.subject == "Fix webhook retry"
        assert c.files == ["src/stripe.py"]

    def test_empty_input(self):
        assert parse_git_log("") == []

    def test_whitespace_only(self):
        assert parse_git_log("   \n\n  ") == []

    def test_no_body(self):
        log = """\
---GNOSIS_COMMIT---
HASH:aaa111
AUTHOR:Eve
DATE:2026-01-01T00:00:00Z
SUBJECT:Initial commit
---GNOSIS_BODY_START---
---GNOSIS_BODY_END---
---GNOSIS_FILES---
README.md
"""
        commits = parse_git_log(log)
        assert len(commits) == 1
        assert commits[0].body == ""
        assert commits[0].files == ["README.md"]

    def test_multiline_body(self):
        log = """\
---GNOSIS_COMMIT---
HASH:bbb222
AUTHOR:Eve
DATE:2026-01-02T00:00:00Z
SUBJECT:Big refactor
---GNOSIS_BODY_START---
Line one.

Line three after blank.
---GNOSIS_BODY_END---
---GNOSIS_FILES---
a.py
"""
        c = parse_git_log(log)[0]
        assert "Line one." in c.body
        assert "Line three after blank." in c.body

    def test_no_files(self):
        log = """\
---GNOSIS_COMMIT---
HASH:ccc333
AUTHOR:Eve
DATE:2026-01-03T00:00:00Z
SUBJECT:Empty commit
---GNOSIS_BODY_START---
---GNOSIS_BODY_END---
---GNOSIS_FILES---
"""
        c = parse_git_log(log)[0]
        assert c.files == []

    def test_incomplete_block_skipped(self):
        """Block without HASH should be skipped."""
        log = """\
---GNOSIS_COMMIT---
AUTHOR:Ghost
DATE:2026-01-01T00:00:00Z
SUBJECT:No hash
---GNOSIS_BODY_START---
---GNOSIS_BODY_END---
---GNOSIS_FILES---
"""
        assert parse_git_log(log) == []


# ---------------------------------------------------------------------------
# group_by_file
# ---------------------------------------------------------------------------


class TestGroupByFile:
    def test_groups_correctly(self):
        commits = _make_commits()
        groups = group_by_file(commits)
        assert set(groups.keys()) == {
            "src/billing.py",
            "src/stripe.py",
            "tests/test_billing.py",
        }

    def test_stripe_has_two_commits(self):
        groups = group_by_file(_make_commits())
        assert len(groups["src/stripe.py"]) == 2

    def test_billing_has_one_commit(self):
        groups = group_by_file(_make_commits())
        assert len(groups["src/billing.py"]) == 1

    def test_order_preserved(self):
        groups = group_by_file(_make_commits())
        hashes = [c.hash for c in groups["src/stripe.py"]]
        assert hashes == ["abc123def456789", "def789abc012345"]

    def test_empty_commits(self):
        assert group_by_file([]) == {}


# ---------------------------------------------------------------------------
# should_include
# ---------------------------------------------------------------------------


class TestShouldInclude:
    def test_no_filters(self):
        assert should_include("src/foo.py", None, None) is True

    def test_include_match(self):
        assert should_include("src/foo.py", "src/*.py", None) is True

    def test_include_no_match(self):
        assert should_include("tests/foo.py", "src/*.py", None) is False

    def test_exclude_match(self):
        assert should_include("package.json", None, "*.json") is False

    def test_exclude_no_match(self):
        assert should_include("src/foo.py", None, "*.json") is True

    def test_include_and_exclude_both_match(self):
        """Exclude takes priority."""
        assert should_include("src/test.json", "src/*", "*.json") is False

    def test_include_match_exclude_no_match(self):
        assert should_include("src/foo.py", "src/*", "*.json") is True

    def test_multiple_include_patterns(self):
        assert should_include("docs/api.md", "src/*.py,docs/*.md", None) is True

    def test_multiple_exclude_patterns(self):
        assert should_include("yarn.lock", None, "*.lock,*.json") is False

    def test_glob_star_matches_slashes(self):
        """fnmatch * matches path separators too — src/* matches nested paths."""
        assert should_include("src/deep/file.py", "src/*", None) is True
        assert should_include("src/file.py", "src/*", None) is True

    def test_empty_string_patterns(self):
        assert should_include("foo.py", "", None) is True
        assert should_include("foo.py", None, "") is True


# ---------------------------------------------------------------------------
# render_history_markdown
# ---------------------------------------------------------------------------


class TestRenderHistoryMarkdown:
    def test_title(self):
        md = render_history_markdown("src/foo.py", _make_commits()[:1])
        assert md.startswith("# src/foo.py — Change History")

    def test_commit_heading(self):
        md = render_history_markdown("src/stripe.py", _make_commits())
        assert "## 2026-02-20: Add billing module (abc123d)" in md

    def test_author_line(self):
        md = render_history_markdown("src/stripe.py", _make_commits())
        assert "Author: Alice" in md

    def test_author_email_in_output(self):
        md = render_history_markdown("src/stripe.py", _make_commits())
        assert "alice@example.com" in md
        assert "bob@example.com" in md

    def test_body_included(self):
        md = render_history_markdown("src/stripe.py", _make_commits())
        assert "charge-before-service" in md

    def test_also_changed(self):
        md = render_history_markdown("src/stripe.py", _make_commits())
        assert "Also changed:" in md
        assert "src/billing.py" in md

    def test_no_self_reference(self):
        """The file itself should not appear in 'Also changed'."""
        md = render_history_markdown("src/stripe.py", _make_commits())
        lines = [ln for ln in md.split("\n") if ln.startswith("Also changed:")]
        for line in lines:
            assert "src/stripe.py" not in line

    def test_empty_commits(self):
        md = render_history_markdown("src/foo.py", [])
        assert "Change History" in md

    def test_short_date(self):
        c = GitCommit(
            hash="aaa",
            author="X",
            author_email="x@test.com",
            date="2026-02-20T10:00:00Z",
            subject="Test",
            body="",
            files=[],
        )
        md = render_history_markdown("f.py", [c])
        assert "2026-02-20" in md

    def test_short_hash(self):
        c = GitCommit(
            hash="abcdefghijklmnop",
            author="X",
            author_email="x@test.com",
            date="2026-01-01",
            subject="Test",
            body="",
            files=[],
        )
        md = render_history_markdown("f.py", [c])
        assert "(abcdefg)" in md

    def test_many_other_files_truncated(self):
        files = [f"file{i}.py" for i in range(20)]
        c = GitCommit(
            hash="aaa",
            author="X",
            author_email="x@test.com",
            date="2026-01-01",
            subject="Bulk",
            body="",
            files=files,
        )
        md = render_history_markdown("file0.py", [c])
        assert "+9 more files" in md


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------


class TestBuildCrossFileLinks:
    def test_shared_commit_creates_links(self):
        """Files sharing a commit should be linked."""
        commits = [
            GitCommit(
                hash="abc123",
                author="Alice",
                author_email="alice@test.com",
                date="2026-02-20",
                subject="Refactor both",
                body="",
                files=["src/a.py", "src/b.py"],
            ),
        ]
        filtered = {"src/a.py": commits, "src/b.py": commits}
        ingested = {"git-history/src/a.py", "git-history/src/b.py"}

        links = _build_cross_file_links(commits, filtered, ingested)
        assert "git-history/src/a.py" in links
        assert "git-history/src/b.py" in links["git-history/src/a.py"]
        assert "git-history/src/a.py" in links["git-history/src/b.py"]

    def test_single_file_commit_no_links(self):
        """A commit touching one file should not create links."""
        commits = [
            GitCommit(
                hash="abc123",
                author="Alice",
                author_email="alice@test.com",
                date="2026-02-20",
                subject="Solo change",
                body="",
                files=["src/a.py"],
            ),
        ]
        filtered = {"src/a.py": commits}
        ingested = {"git-history/src/a.py"}

        links = _build_cross_file_links(commits, filtered, ingested)
        assert links == {}

    def test_only_ingested_paths_linked(self):
        """Only files in ingested_paths should appear in links."""
        commits = [
            GitCommit(
                hash="abc123",
                author="Alice",
                author_email="alice@test.com",
                date="2026-02-20",
                subject="Multi-file",
                body="",
                files=["src/a.py", "src/b.py", "src/c.py"],
            ),
        ]
        filtered = {"src/a.py": commits, "src/b.py": commits, "src/c.py": commits}
        # Only a and b were actually ingested
        ingested = {"git-history/src/a.py", "git-history/src/b.py"}

        links = _build_cross_file_links(commits, filtered, ingested)
        assert "git-history/src/a.py" in links
        assert "git-history/src/b.py" in links["git-history/src/a.py"]
        # c should not appear as it wasn't ingested
        for targets in links.values():
            assert "git-history/src/c.py" not in targets


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_for_different_input(self):
        assert _content_hash("a") != _content_hash("b")

    def test_length(self):
        assert len(_content_hash("test")) == 16


# ---------------------------------------------------------------------------
# GitIngestConfig defaults
# ---------------------------------------------------------------------------


class TestGitIngestConfig:
    def test_defaults(self):
        cfg = GitIngestConfig()
        assert cfg.since is None
        assert cfg.max_commits == 10
        assert cfg.include is None
        assert cfg.exclude is None
        assert cfg.embed is False
        assert cfg.dry_run is False
        assert cfg.merge_commits is False

    def test_frozen(self):
        cfg = GitIngestConfig()
        with pytest.raises(AttributeError):
            cfg.since = "1m"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration: ingest_git with a real temp repo
# ---------------------------------------------------------------------------


def _create_temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with a few commits."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Tester"],
        check=True,
        capture_output=True,
    )

    # Commit 1
    (repo / "README.md").write_text("# Hello\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Initial commit"],
        check=True,
        capture_output=True,
    )

    # Commit 2
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Add main module"],
        check=True,
        capture_output=True,
    )

    # Commit 3 — modify existing
    (repo / "src" / "main.py").write_text("print('hello world')\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Update greeting"],
        check=True,
        capture_output=True,
    )

    return repo


class TestIngestGitIntegration:
    """Integration tests using a real temp git repo + SQLite backend."""

    def test_dry_run(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig(dry_run=True)

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        assert len(results) > 0
        assert all(r.action == "dry-run" for r in results)

    def test_real_ingest(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig()

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        ingested = [r for r in results if r.action == "ingested"]
        assert len(ingested) >= 2  # README.md + src/main.py

    def test_incremental_skip(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig()

        # First run
        asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        # Second run — should be unchanged
        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        unchanged = [r for r in results if r.action == "unchanged"]
        assert len(unchanged) >= 2

    def test_include_filter(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig(include="src/*")

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        for r in results:
            if r.action in ("ingested", "dry-run"):
                assert "src/" in r.path

    def test_exclude_filter(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig(exclude="README.md")

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        for r in results:
            if r.action == "ingested":
                assert "README.md" not in r.path

    def test_not_a_repo(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        cfg = GnosisMcpConfig(database_url=f"sqlite:///{tmp_path}/test.db")
        git_cfg = GitIngestConfig()

        with pytest.raises(ValueError, match="Not a git repository"):
            asyncio.run(ingest_git(cfg, str(tmp_path), git_cfg))

    def test_max_commits(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig(max_commits=1, dry_run=True)

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        # Each file should have at most 1 commit
        for r in results:
            assert r.commits <= 1

    def test_author_filter(self, tmp_path: Path):
        """--author filters commits by author name."""
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        # Use a non-existent author — should find no commits
        git_cfg = GitIngestConfig(author="NonExistentAuthor12345", dry_run=True)

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        # Either skipped or empty — no commits from this author
        assert all(r.action in ("skipped", "dry-run") for r in results)
        if any(r.action == "dry-run" for r in results):
            # Shouldn't happen for a non-existent author
            pass
        else:
            assert any(r.detail == "No commits found" for r in results)

    def test_until_filter(self, tmp_path: Path):
        """--until filters commits by end date."""
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        # Use a date far in the past — should find no commits
        git_cfg = GitIngestConfig(until="2000-01-01", dry_run=True)

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        assert all(r.action == "skipped" for r in results)

    def test_force_reingest(self, tmp_path: Path):
        """--force re-ingests even if content hash is unchanged."""
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")

        # First run
        asyncio.run(ingest_git(cfg, str(repo), GitIngestConfig()))

        # Second run without force — should be unchanged
        r2 = asyncio.run(ingest_git(cfg, str(repo), GitIngestConfig()))
        assert all(r.action == "unchanged" for r in r2 if r.action != "skipped")

        # Third run with force — should re-ingest
        r3 = asyncio.run(ingest_git(cfg, str(repo), GitIngestConfig(force=True)))
        ingested = [r for r in r3 if r.action == "ingested"]
        assert len(ingested) >= 2

    def test_cross_file_links(self, tmp_path: Path):
        """Multi-file commits should create cross-file relates_to links."""
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git
        from gnosis_mcp.backend import create_backend

        # Create repo with a multi-file commit
        repo = tmp_path / "cross-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Tester"],
            check=True,
            capture_output=True,
        )
        # Commit touching multiple files at once
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("# module a\n")
        (repo / "src" / "b.py").write_text("# module b\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "Add both modules"],
            check=True,
            capture_output=True,
        )

        db_path = tmp_path / "cross.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig()

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        ingested = [r for r in results if r.action == "ingested"]
        assert len(ingested) >= 2

        # Verify cross-file links were created
        backend = create_backend(cfg)
        asyncio.run(backend.startup())
        try:
            related = asyncio.run(backend.get_related("git-history/src/a.py"))
            if related is not None:
                related_paths = [r["related_path"] for r in related]
                assert "git-history/src/b.py" in related_paths
        finally:
            asyncio.run(backend.shutdown())

    def test_doc_path_prefixed(self, tmp_path: Path):
        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.parsers.git_history import ingest_git

        repo = _create_temp_repo(tmp_path)
        db_path = tmp_path / "test.db"
        cfg = GnosisMcpConfig(database_url=f"sqlite:///{db_path}")
        git_cfg = GitIngestConfig()

        results = asyncio.run(ingest_git(cfg, str(repo), git_cfg))
        for r in results:
            if r.action == "ingested":
                assert r.path.startswith("git-history/")
