"""Tests for gnosis_mcp.watch — file change detection and watcher lifecycle."""

from pathlib import Path

import pytest

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.watch import _process_changes, detect_changes, scan_mtimes, start_watcher


# ---------------------------------------------------------------------------
# scan_mtimes
# ---------------------------------------------------------------------------


class TestScanMtimes:
    def test_empty_dir(self, tmp_path):
        assert scan_mtimes(tmp_path) == {}

    def test_finds_supported_files(self, tmp_path):
        (tmp_path / "a.md").write_text("# A")
        (tmp_path / "b.md").write_text("# B")
        (tmp_path / "c.txt").write_text("plain text")
        (tmp_path / "d.py").write_text("# not docs")
        result = scan_mtimes(tmp_path)
        assert len(result) == 3  # .md + .txt are supported
        assert not any(p.suffix == ".py" for p in result)

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.md").write_text("# Root")
        (sub / "nested.md").write_text("# Nested")
        result = scan_mtimes(tmp_path)
        assert len(result) == 2

    def test_single_md_file(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Doc")
        result = scan_mtimes(f)
        assert len(result) == 1
        assert f in result

    def test_single_txt_file(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("plain text")
        result = scan_mtimes(f)
        assert len(result) == 1  # .txt is now supported

    def test_single_unsupported_file(self, tmp_path):
        f = tmp_path / "doc.py"
        f.write_text("# python")
        result = scan_mtimes(f)
        assert len(result) == 0

    def test_nonexistent(self, tmp_path):
        result = scan_mtimes(tmp_path / "nope")
        assert result == {}

    def test_mtime_is_float(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Doc")
        result = scan_mtimes(tmp_path)
        assert isinstance(list(result.values())[0], float)


# ---------------------------------------------------------------------------
# detect_changes
# ---------------------------------------------------------------------------


class TestDetectChanges:
    def test_no_changes(self):
        snap = {Path("a.md"): 1.0, Path("b.md"): 2.0}
        changed, deleted = detect_changes(snap, snap.copy())
        assert changed == []
        assert deleted == []

    def test_modified_file(self):
        old = {Path("a.md"): 1.0}
        new = {Path("a.md"): 2.0}
        changed, deleted = detect_changes(old, new)
        assert changed == [Path("a.md")]
        assert deleted == []

    def test_new_file(self):
        old = {Path("a.md"): 1.0}
        new = {Path("a.md"): 1.0, Path("b.md"): 1.0}
        changed, deleted = detect_changes(old, new)
        assert changed == [Path("b.md")]
        assert deleted == []

    def test_deleted_file(self):
        old = {Path("a.md"): 1.0, Path("b.md"): 2.0}
        new = {Path("a.md"): 1.0}
        changed, deleted = detect_changes(old, new)
        assert changed == []
        assert deleted == [Path("b.md")]

    def test_mixed_changes(self):
        old = {Path("a.md"): 1.0, Path("b.md"): 2.0}
        new = {Path("a.md"): 9.0, Path("c.md"): 3.0}
        changed, deleted = detect_changes(old, new)
        assert set(changed) == {Path("a.md"), Path("c.md")}
        assert deleted == [Path("b.md")]

    def test_empty_to_files(self):
        changed, deleted = detect_changes({}, {Path("a.md"): 1.0})
        assert changed == [Path("a.md")]
        assert deleted == []

    def test_files_to_empty(self):
        changed, deleted = detect_changes({Path("a.md"): 1.0}, {})
        assert changed == []
        assert deleted == [Path("a.md")]


# ---------------------------------------------------------------------------
# start_watcher lifecycle
# ---------------------------------------------------------------------------


class TestStartWatcher:
    def test_starts_and_stops(self, tmp_path, sqlite_config):
        (tmp_path / "doc.md").write_text("# Test\n\nSome content for testing watcher.")
        thread = start_watcher(
            str(tmp_path), sqlite_config, embed=False, interval=0.2
        )
        assert thread.is_alive()
        thread.stop_event.set()
        thread.join(timeout=3)
        assert not thread.is_alive()

    def test_daemon_thread(self, tmp_path, sqlite_config):
        thread = start_watcher(
            str(tmp_path), sqlite_config, embed=False, interval=0.2
        )
        assert thread.daemon is True
        thread.stop_event.set()
        thread.join(timeout=3)

    def test_thread_name(self, tmp_path, sqlite_config):
        thread = start_watcher(
            str(tmp_path), sqlite_config, embed=False, interval=0.2
        )
        assert thread.name == "gnosis-watcher"
        thread.stop_event.set()
        thread.join(timeout=3)


# ---------------------------------------------------------------------------
# _process_changes
# ---------------------------------------------------------------------------


class TestProcessChanges:
    @pytest.mark.asyncio
    async def test_re_ingests_files(self, tmp_path):
        """_process_changes re-ingests changed files."""
        doc = tmp_path / "test.md"
        doc.write_text("# Test\n\nThis is test content for the watcher re-ingest test case.")

        config = GnosisMcpConfig(
            database_url=str(tmp_path / "watch.db"),
            backend="sqlite",
        )

        count = await _process_changes(str(tmp_path), config, embed=False)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_empty_dir_zero_ingested(self, tmp_path):
        """Empty directory yields 0 ingested."""
        config = GnosisMcpConfig(
            database_url=str(tmp_path / "watch.db"),
            backend="sqlite",
        )

        count = await _process_changes(str(tmp_path), config, embed=False)
        assert count == 0

    @pytest.mark.asyncio
    async def test_second_run_unchanged(self, tmp_path):
        """Second run with same content returns 0 (content hashing skips unchanged)."""
        doc = tmp_path / "test.md"
        doc.write_text("# Test\n\nThis is test content for the watcher unchanged test case.")

        config = GnosisMcpConfig(
            database_url=str(tmp_path / "watch.db"),
            backend="sqlite",
        )

        first = await _process_changes(str(tmp_path), config, embed=False)
        assert first >= 1

        second = await _process_changes(str(tmp_path), config, embed=False)
        assert second == 0
