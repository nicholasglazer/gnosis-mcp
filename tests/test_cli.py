"""Tests for CLI utilities and command handlers."""

import argparse
import logging
import os
import sys
import types

import pytest

from gnosis_mcp.cli import (
    _apply_serve_overrides,
    _detect_local_provider,
    _format_bytes,
    _mask_url,
    _missing_schema_parts,
    cmd_check,
    cmd_init_db,
    cmd_serve,
    cmd_stats,
    main,
)
from gnosis_mcp.config import GnosisMcpConfig


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


def _use_sqlite_db(monkeypatch, db_path) -> None:
    """Point config construction at an isolated SQLite database."""
    monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", str(db_path))
    monkeypatch.setenv("GNOSIS_MCP_BACKEND", "sqlite")


def _isolate_config_env(monkeypatch) -> None:
    """Drop ambient DB/transport config so a test sees only what it sets."""
    for var in ("GNOSIS_MCP_DATABASE_URL", "DATABASE_URL", "GNOSIS_MCP_TRANSPORT"):
        monkeypatch.delenv(var, raising=False)


class TestMissingSchemaParts:
    """`_missing_schema_parts` decides what makes `check` unhealthy."""

    def test_initialized_sqlite_reports_nothing_missing(self):
        health = {
            "backend": "sqlite",
            "chunks_table_exists": True,
            "fts_table_exists": True,
            "links_table_exists": True,
        }
        assert _missing_schema_parts(health) == []

    def test_uninitialized_sqlite_reports_every_part(self):
        health = {
            "backend": "sqlite",
            "chunks_table_exists": False,
            "fts_table_exists": False,
            "links_table_exists": False,
        }
        assert _missing_schema_parts(health) == ["chunks table", "FTS5 index", "links table"]

    def test_postgres_without_fts_key_is_healthy(self):
        """PostgreSQL reports no FTS5 key — its absence must not imply failure."""
        health = {"backend": "postgres", "chunks_table_exists": True, "links_table_exists": True}
        assert _missing_schema_parts(health) == []

    def test_unreported_chunks_key_is_not_a_claim(self):
        """A backend that never reports the key is not asserting the table is gone.

        Both shipped backends do report it; this pins the contract the docstring
        states so a future backend that stays silent is not called unhealthy.
        """
        assert _missing_schema_parts({"backend": "future"}) == []

    def test_missing_fts_alone_is_unhealthy(self):
        health = {
            "backend": "sqlite",
            "chunks_table_exists": True,
            "fts_table_exists": False,
            "links_table_exists": True,
        }
        assert _missing_schema_parts(health) == ["FTS5 index"]


class TestCmdCheckExitStatus:
    """`cmd_check` returns the process status `main()` propagates."""

    def test_uninitialized_db_returns_1(self, monkeypatch, tmp_path, caplog):
        caplog.set_level(logging.INFO)
        _use_sqlite_db(monkeypatch, tmp_path / "never-created.db")

        assert cmd_check(argparse.Namespace()) == 1
        assert "Chunks table: does not exist" in caplog.text
        assert "unhealthy" in caplog.text
        assert "exit 1" in caplog.text

    def test_existing_but_empty_db_returns_1(self, monkeypatch, tmp_path, caplog):
        caplog.set_level(logging.INFO)
        db = tmp_path / "empty.db"
        db.touch()
        _use_sqlite_db(monkeypatch, db)

        assert cmd_check(argparse.Namespace()) == 1
        assert "unhealthy" in caplog.text

    def test_initialized_db_returns_0(self, monkeypatch, tmp_path, caplog):
        caplog.set_level(logging.INFO)
        db = tmp_path / "healthy.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        caplog.clear()

        assert cmd_check(argparse.Namespace()) == 0
        assert "All checks passed." in caplog.text
        assert "healthy" in caplog.text
        assert "unhealthy" not in caplog.text

    def test_unstartable_backend_returns_1(self, monkeypatch, tmp_path, caplog):
        """A path that cannot be opened (parent is a file) is an unhealthy backend."""
        caplog.set_level(logging.INFO)
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        _use_sqlite_db(monkeypatch, blocker / "nested" / "docs.db")

        assert cmd_check(argparse.Namespace()) == 1
        assert "Cannot start the sqlite backend" in caplog.text
        assert "unhealthy" in caplog.text

    def test_main_propagates_nonzero_status(self, monkeypatch, tmp_path):
        """main() must turn cmd_check's 1 into a SystemExit(1) process status."""
        _use_sqlite_db(monkeypatch, tmp_path / "uninitialized.db")
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp", "check"])

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_main_returns_normally_on_healthy_db(self, monkeypatch, tmp_path):
        db = tmp_path / "healthy-main.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp", "check"])

        assert main() is None


class TestApplyServeOverrides:
    """`serve` flags override the GNOSIS_MCP_* env vars via the env itself."""

    def test_flags_override_env(self, monkeypatch):
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "5")
        monkeypatch.setenv("GNOSIS_MCP_CONTENT_PREVIEW_CHARS", "100")

        _apply_serve_overrides(argparse.Namespace(search_limit_max=42, content_preview_chars=777))

        assert os.environ["GNOSIS_MCP_SEARCH_LIMIT_MAX"] == "42"
        assert os.environ["GNOSIS_MCP_CONTENT_PREVIEW_CHARS"] == "777"
        cfg = GnosisMcpConfig.from_env()
        assert cfg.search_limit_max == 42
        assert cfg.content_preview_chars == 777

    def test_flags_override_defaults(self, monkeypatch):
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "20")
        monkeypatch.setenv("GNOSIS_MCP_CONTENT_PREVIEW_CHARS", "200")

        _apply_serve_overrides(argparse.Namespace(search_limit_max=3, content_preview_chars=64))

        cfg = GnosisMcpConfig.from_env()
        assert cfg.search_limit_max == 3
        assert cfg.content_preview_chars == 64

    def test_unset_flags_leave_env_alone(self, monkeypatch):
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "5")
        monkeypatch.setenv("GNOSIS_MCP_CONTENT_PREVIEW_CHARS", "100")

        _apply_serve_overrides(
            argparse.Namespace(search_limit_max=None, content_preview_chars=None)
        )

        cfg = GnosisMcpConfig.from_env()
        assert cfg.search_limit_max == 5
        assert cfg.content_preview_chars == 100

    def test_invalid_flag_value_fails_config_validation(self, monkeypatch):
        """A bad CLI value hits the same validation as the env var."""
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "20")

        _apply_serve_overrides(argparse.Namespace(search_limit_max=0, content_preview_chars=None))

        with pytest.raises(ValueError, match="GNOSIS_MCP_SEARCH_LIMIT_MAX"):
            GnosisMcpConfig.from_env()


class TestCmdServeOverrides:
    def test_serve_sets_env_before_building_config(self, monkeypatch):
        """cmd_serve must export the flags, not patch its own config object.

        The MCP tools build a *second* config via `from_env()` inside
        `db.app_lifespan()`, so only the environment carries the override.
        """
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_SEARCH_LIMIT_MAX", "20")
        monkeypatch.setenv("GNOSIS_MCP_CONTENT_PREVIEW_CHARS", "200")

        served: dict[str, str | None] = {}

        class _FakeMcp:
            settings = types.SimpleNamespace(host=None, port=None)

            def run(self, transport=None):
                served["transport"] = transport

        # Stub the server module: importing the real one is unnecessary here and
        # another change owns server.py.
        fake_server = types.ModuleType("gnosis_mcp.server")
        fake_server.mcp = _FakeMcp()
        monkeypatch.setitem(sys.modules, "gnosis_mcp.server", fake_server)

        cmd_serve(
            argparse.Namespace(
                transport=None,
                host=None,
                port=None,
                ingest=None,
                watch=None,
                rest=False,
                search_limit_max=7,
                content_preview_chars=321,
            )
        )

        assert served["transport"] == "stdio"
        assert os.environ["GNOSIS_MCP_SEARCH_LIMIT_MAX"] == "7"
        assert GnosisMcpConfig.from_env().content_preview_chars == 321


class TestServeHelp:
    def test_new_flags_are_documented(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp", "serve", "--help"])

        with pytest.raises(SystemExit, match="0"):
            main()

        out = capsys.readouterr().out
        assert "--search-limit-max" in out
        assert "--content-preview-chars" in out
        assert "GNOSIS_MCP_SEARCH_LIMIT_MAX" in out
        assert "GNOSIS_MCP_CONTENT_PREVIEW_CHARS" in out
