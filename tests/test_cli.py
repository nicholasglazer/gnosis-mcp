"""Tests for CLI utilities and command handlers."""

import argparse
import sys
import types

import pytest

from gnosis_mcp.cli import (
    _detect_local_provider,
    _format_bytes,
    _mask_url,
    cmd_init_db,
    cmd_stats,
    main,
)


class TestMaskUrl:
    def test_masks_password(self):
        url = "postgresql://user:secretpass@localhost:5432/db"
        assert _mask_url(url) == "postgresql://user:***@localhost:5432/db"

    def test_preserves_no_password(self):
        url = "postgresql://localhost/db"
        assert _mask_url(url) == "postgresql://localhost/db"

    def test_masks_url_encoded_password(self):
        url = "postgresql://admin:p%40ss%23word@host:5432/db"
        assert _mask_url(url) == "postgresql://admin:***@host:5432/db"

    def test_preserves_simple_url(self):
        url = "localhost"
        assert _mask_url(url) == "localhost"

    def test_handles_at_in_password(self):
        # rsplit("@", 1) handles this — takes the LAST @
        url = "postgresql://user:p@ss@host:5432/db"
        result = _mask_url(url)
        assert "***@host:5432/db" in result
        assert "p@ss" not in result


class TestHumanSize:
    def test_bytes(self):
        assert _format_bytes(512) == "512 B"

    def test_kilobytes(self):
        assert _format_bytes(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _format_bytes(5 * 1024 * 1024) == "5.0 MB"

    def test_zero(self):
        assert _format_bytes(0) == "0 B"

    def test_large(self):
        result = _format_bytes(1_500_000_000)
        assert "GB" in result


class TestMainNoArgs:
    def test_no_command_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp"])
        with pytest.raises(SystemExit, match="1"):
            main()

    def test_version_flag(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp", "--version"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        from gnosis_mcp import __version__
        assert f"gnosis-mcp {__version__}" in out


class TestDetectLocalProvider:
    def test_returns_true_when_available(self, monkeypatch):
        mock_ort = types.ModuleType("onnxruntime")
        mock_tok = types.ModuleType("tokenizers")
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tok)
        assert _detect_local_provider() is True

    def test_returns_false_when_onnxruntime_missing(self, monkeypatch):
        # Setting a module to None in sys.modules causes ImportError
        monkeypatch.setitem(sys.modules, "onnxruntime", None)
        assert _detect_local_provider() is False

    def test_returns_false_when_tokenizers_missing(self, monkeypatch):
        mock_ort = types.ModuleType("onnxruntime")
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", None)
        assert _detect_local_provider() is False


class TestCmdInitDbDryRun:
    def test_sqlite_dry_run(self, monkeypatch, capsys):
        """--dry-run prints SQLite DDL without executing."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        args = argparse.Namespace(dry_run=True)
        cmd_init_db(args)
        out = capsys.readouterr().out
        assert "CREATE TABLE" in out
        assert "documentation_chunks" in out
        assert "CREATE VIRTUAL TABLE" in out  # FTS5

    def test_postgres_dry_run(self, monkeypatch, capsys):
        """--dry-run with PostgreSQL prints PG-specific DDL."""
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", "postgresql://localhost/test")

        args = argparse.Namespace(dry_run=True)
        cmd_init_db(args)
        out = capsys.readouterr().out
        assert "CREATE TABLE" in out
        assert "tsvector" in out


class TestCmdStats:
    def test_stats_sqlite(self, monkeypatch, tmp_path, capsys):
        """cmd_stats runs against an empty SQLite database."""
        db_path = str(tmp_path / "stats.db")
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
        monkeypatch.setenv("GNOSIS_MCP_BACKEND", "sqlite")

        # Initialize schema first
        init_args = argparse.Namespace(dry_run=False)
        cmd_init_db(init_args)

        args = argparse.Namespace()
        cmd_stats(args)
        out = capsys.readouterr().out
        assert "Documents:" in out
        assert "Chunks:" in out
