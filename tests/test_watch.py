"""Tests for gnosis_mcp.watch — file change detection and watcher lifecycle."""

import time
from pathlib import Path

import pytest

from gnosis_mcp.watch import detect_changes, scan_mtimes, start_watcher


# ---------------------------------------------------------------------------
# scan_mtimes
# ---------------------------------------------------------------------------


class TestScanMtimes:
    def test_empty_dir(self, tmp_path):
        assert scan_mtimes(tmp_path) == {}

    def test_finds_md_files(self, tmp_path):
        (tmp_path / "a.md").write_text("# A")
        (tmp_path / "b.md").write_text("# B")
        (tmp_path / "c.txt").write_text("not markdown")
        result = scan_mtimes(tmp_path)
        assert len(result) == 2
        assert all(p.suffix == ".md" for p in result)

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

    def test_single_non_md_file(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("not markdown")
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
