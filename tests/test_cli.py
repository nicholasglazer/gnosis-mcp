"""Tests for CLI utilities and command handlers."""

import argparse
import asyncio
import csv
import io
import json
import logging
import os
import sys
import types

import pytest

from gnosis_mcp import clients as cli_clients
from gnosis_mcp.cli import (
    _apply_serve_overrides,
    _check_reranker,
    _detect_local_provider,
    _format_bytes,
    _is_missing_schema_error,
    _mask_url,
    _missing_schema_parts,
    _require_schema,
    cmd_check,
    cmd_doctor,
    cmd_export,
    cmd_fix_link_types,
    cmd_init_db,
    cmd_serve,
    cmd_setup,
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


class TestMissingSchemaGuidance:
    """A never-initialized database must not dump an aiosqlite traceback.

    Regression: `search` and `stats` (and six more subcommands) raised the raw
    `sqlite3.OperationalError: no such table: documentation_chunks_fts` with a
    full traceback and no hint, while the MCP tools and `gnosis-mcp check` both
    pointed at `gnosis-mcp init-db`.
    """

    UNINITIALIZED_COMMANDS = [
        ["search", "anything"],
        ["stats"],
        ["export", "-f", "json"],
        ["export", "-f", "csv"],
        ["embed", "--dry-run"],
        ["prune", "."],
        ["diff", "."],
        ["cleanup", "--days", "1"],
        ["fix-link-types"],
    ]

    @pytest.mark.parametrize("argv", UNINITIALIZED_COMMANDS, ids=lambda argv: argv[0])
    def test_exits_1_with_guidance(self, monkeypatch, tmp_path, caplog, argv):
        caplog.set_level(logging.ERROR)
        _use_sqlite_db(monkeypatch, tmp_path / f"fresh-{argv[0]}.db")
        monkeypatch.setenv("GNOSIS_MCP_EMBED_PROVIDER", "local")
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp", *argv])

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

        guidance = [r for r in caplog.records if "init-db" in r.getMessage()]
        assert guidance, f"no init-db guidance logged; got: {caplog.text}"
        assert "gnosis-mcp ingest <path>" in guidance[0].getMessage()
        # Guidance, not a logged traceback.
        assert guidance[0].exc_info is None

    def test_command_handler_returns_1(self, monkeypatch, tmp_path, caplog):
        """The status travels as a return value, matching `check`'s convention."""
        caplog.set_level(logging.ERROR)
        _use_sqlite_db(monkeypatch, tmp_path / "fresh-stats.db")

        assert cmd_stats(argparse.Namespace()) == 1
        assert "not initialized" in caplog.text

    def test_initialized_db_still_succeeds(self, monkeypatch, tmp_path):
        _use_sqlite_db(monkeypatch, tmp_path / "healthy-stats.db")
        cmd_init_db(argparse.Namespace(dry_run=False))
        monkeypatch.setattr(sys, "argv", ["gnosis-mcp", "stats"])

        assert main() is None

    def test_unrelated_errors_are_not_swallowed(self):
        @_require_schema
        def boom(args):
            raise ValueError("not a schema problem")

        with pytest.raises(ValueError, match="not a schema problem"):
            boom(argparse.Namespace())


class TestIsMissingSchemaError:
    def test_detects_sqlite_missing_table(self):
        import sqlite3

        assert _is_missing_schema_error(
            sqlite3.OperationalError("no such table: documentation_chunks_fts")
        )

    def test_detects_postgres_undefined_table(self):
        class UndefinedTableError(Exception):
            pass

        assert _is_missing_schema_error(
            UndefinedTableError('relation "documentation_chunks" does not exist')
        )

    def test_ignores_unrelated_errors(self):
        assert not _is_missing_schema_error(ValueError("bad query"))
        assert not _is_missing_schema_error(RuntimeError("connection refused"))


class TestCmdExportCsv:
    """`export -f csv` must report real chunk rows, not paragraph counts."""

    def _seed(self, monkeypatch, tmp_path, chunks: list[str]) -> GnosisMcpConfig:
        from gnosis_mcp.backend import create_backend

        _use_sqlite_db(monkeypatch, tmp_path / "export.db")
        config = GnosisMcpConfig.from_env()

        async def _run() -> None:
            backend = create_backend(config)
            await backend.startup()
            await backend.init_schema()
            if chunks:
                await backend.upsert_doc(
                    "guides/two-chunks.md",
                    chunks,
                    title="Two Chunks",
                    category="guides",
                )
            await backend.shutdown()

        asyncio.run(_run())
        return config

    def test_reports_true_chunk_count(self, monkeypatch, tmp_path, capsys):
        # Two chunks, three paragraphs each. The old formula
        # (`content.count("\n\n") + 1`) reported 6 for this document.
        chunks = ["alpha one\n\nalpha two\n\nalpha three", "beta one\n\nbeta two\n\nbeta three"]
        config = self._seed(monkeypatch, tmp_path, chunks)

        cmd_export(argparse.Namespace(format="csv", category=None))
        rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))

        assert rows[0] == ["file_path", "title", "category", "chunks"]
        assert rows[1][0] == "guides/two-chunks.md"
        assert rows[1][3] == "2", f"expected the 2 real chunks, got: {rows[1]}"

        # Pin the fixture's shape: the paragraph count and the chunk count differ,
        # so this test fails if anyone reintroduces the paragraph approximation.
        from gnosis_mcp.backend import create_backend

        async def _content() -> str:
            backend = create_backend(config)
            await backend.startup()
            docs = await backend.export_docs()
            await backend.shutdown()
            return docs[0]["content"]

        content = asyncio.run(_content())
        assert content.count("\n\n") + 1 == 6

    def test_empty_db_writes_header_only(self, monkeypatch, tmp_path, capsys):
        self._seed(monkeypatch, tmp_path, [])

        cmd_export(argparse.Namespace(format="csv", category=None))
        rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))

        assert rows == [["file_path", "title", "category", "chunks"]]


class TestServeRerankerProbe:
    """`serve` must say so when reranking is enabled but its model is unfetchable.

    A broken `GNOSIS_MCP_RERANK_MODEL` used to surface only as a "Rerank failed"
    traceback on the first search, after which searches silently returned
    unranked results — which is how a default pointing at a non-existent repo
    (HTTP 401) went unnoticed.
    """

    def _config(self, monkeypatch, tmp_path, model: str = "org/does-not-exist"):
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", str(tmp_path / "probe.db"))
        monkeypatch.setenv("GNOSIS_MCP_RERANK_ENABLED", "true")
        monkeypatch.setenv("GNOSIS_MCP_RERANK_MODEL", model)
        return GnosisMcpConfig.from_env()

    def test_warns_loudly_when_model_unavailable(self, monkeypatch, tmp_path, caplog):
        caplog.set_level(logging.INFO)
        config = self._config(monkeypatch, tmp_path)

        from gnosis_mcp import rerank as rr

        monkeypatch.setattr(rr, "check_model_available", lambda *a, **kw: (False, "HTTP 401"))
        _check_reranker(config)

        assert "cannot be fetched" in caplog.text
        assert "HTTP 401" in caplog.text
        assert "GNOSIS_MCP_RERANK_MODEL" in caplog.text
        assert rr.DEFAULT_MODEL in caplog.text

    def test_logs_info_when_model_available(self, monkeypatch, tmp_path, caplog):
        caplog.set_level(logging.INFO)
        config = self._config(monkeypatch, tmp_path)

        from gnosis_mcp import rerank as rr

        monkeypatch.setattr(rr, "check_model_available", lambda *a, **kw: (True, "cached"))
        _check_reranker(config)

        assert "is available" in caplog.text
        assert "cannot be fetched" not in caplog.text

    def test_probe_failure_never_blocks_serve(self, monkeypatch, tmp_path, caplog):
        caplog.set_level(logging.DEBUG)
        config = self._config(monkeypatch, tmp_path)

        from gnosis_mcp import rerank as rr

        def _explode(*args, **kwargs):
            raise OSError("network down")

        monkeypatch.setattr(rr, "check_model_available", _explode)
        _check_reranker(config)  # must not raise

        assert "cannot be fetched" not in caplog.text

    def test_probe_skipped_when_reranking_disabled(self, monkeypatch, tmp_path):
        _isolate_config_env(monkeypatch)
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", str(tmp_path / "probe.db"))
        monkeypatch.delenv("GNOSIS_MCP_RERANK_ENABLED", raising=False)
        config = GnosisMcpConfig.from_env()

        from gnosis_mcp import rerank as rr

        def _unexpected(*args, **kwargs):  # pragma: no cover — asserts it is not called
            raise AssertionError("probe must not run when reranking is off")

        monkeypatch.setattr(rr, "check_model_available", _unexpected)
        _check_reranker(config)


class TestFixLinkTypesMigration:
    """`fix-link-types` must survive the database state it exists to repair.

    `documentation_links` is UNIQUE on (source_path, target_path, relation_type)
    in both backends, and the ingest path already writes the typed rows. On a
    database carrying a legacy `relates_to` row *and* its typed twin the UPDATE
    collided with the existing row and raised IntegrityError, so the migration
    aborted before its second statement ran.
    """

    @staticmethod
    def _seed(db_path, rows):
        import sqlite3

        con = sqlite3.connect(db_path)
        for path in ("git-history/a.md", "git-history/b.md", "src/module.py"):
            con.execute(
                "INSERT OR IGNORE INTO documentation_chunks "
                "(file_path, chunk_index, title, content, category) "
                "VALUES (?,0,'t','body','c')",
                (path,),
            )
        con.executemany(
            "INSERT INTO documentation_links (source_path, target_path, relation_type) "
            "VALUES ('git-history/a.md', ?, ?)",
            rows,
        )
        con.commit()
        con.close()

    @staticmethod
    def _links(db_path):
        import sqlite3

        con = sqlite3.connect(db_path)
        try:
            return sorted(
                con.execute("SELECT target_path, relation_type FROM documentation_links")
            )
        finally:
            con.close()

    def test_duplicate_typed_row_does_not_abort_the_migration(self, monkeypatch, tmp_path):
        """The exact crash: legacy row plus its typed twin present."""
        db = tmp_path / "dup.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        self._seed(db, [("git-history/b.md", "git_co_change"), ("git-history/b.md", "relates_to")])

        cmd_fix_link_types(argparse.Namespace())  # must not raise

        assert self._links(db) == [("git-history/b.md", "git_co_change")]

    def test_pure_legacy_rows_are_still_migrated(self, monkeypatch, tmp_path):
        """The migration's actual purpose, which the dedupe must not break."""
        db = tmp_path / "legacy.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        self._seed(db, [("git-history/b.md", "relates_to"), ("src/module.py", "relates_to")])

        cmd_fix_link_types(argparse.Namespace())

        assert self._links(db) == [
            ("git-history/b.md", "git_co_change"),
            ("src/module.py", "git_ref"),
        ]

    def test_second_run_is_idempotent(self, monkeypatch, tmp_path):
        db = tmp_path / "twice.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        self._seed(db, [("git-history/b.md", "relates_to")])

        cmd_fix_link_types(argparse.Namespace())
        cmd_fix_link_types(argparse.Namespace())

        assert self._links(db) == [("git-history/b.md", "git_co_change")]


class TestCmdSetup:
    """`setup` is the reproducible half of an install."""

    @pytest.fixture
    def harness_home(self, monkeypatch, tmp_path):
        """A throwaway $DSH_HOME, so no test can touch the developer's own."""
        home = tmp_path / "dsh"
        (home / "profiles" / "web").mkdir(parents=True)
        (home / "profiles" / "web" / "cordis.yml").write_text("[]\n")
        monkeypatch.setenv("DSH_HOME", str(home))
        # Path.home() reads $HOME, so this keeps `scan` off the developer's real
        # ~/.claude.json — otherwise every doctor assertion depends on their machine.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setattr(cli_clients.shutil, "which", lambda _n: None)
        return home

    def test_preview_names_the_path_and_changes_nothing(self, harness_home, capsys):
        code = cmd_setup(argparse.Namespace(
            client=["dsh"], write=False, no_cli=False, dsh_profile=None, json=False, list_clients=False
        ))

        out = capsys.readouterr().out
        assert code == 0
        assert str(harness_home / "profiles" / "web" / "cordis.patch.yml") in out
        assert not (harness_home / "profiles" / "web" / "cordis.patch.yml").exists()

    def test_write_installs_a_row_the_harness_can_parse(self, harness_home):
        """The real proof of reproducibility: a fresh home becomes a wired home."""
        code = cmd_setup(argparse.Namespace(
            client=["dsh"], write=True, no_cli=False, dsh_profile=None, json=False, list_clients=False
        ))

        patch = (harness_home / "profiles" / "web" / "cordis.patch.yml").read_text()
        assert code == 0
        assert "- id: mcp-gnosis" in patch
        assert "name: '@deepseek-ai/dsh-mcp-client'" in patch
        # PyYAML is not a dependency, so the check is the shape the loader wants:
        # the block is a top-level list item, after its explanatory comments.
        assert "- insert:" in patch
        assert "failOnStartupError: false" in patch

    def test_second_write_is_a_no_op(self, harness_home):
        args = argparse.Namespace(
            client=["dsh"], write=True, no_cli=False, dsh_profile=None, json=False, list_clients=False
        )
        cmd_setup(args)
        patch = harness_home / "profiles" / "web" / "cordis.patch.yml"
        agents = harness_home / "AGENTS.md"
        first = (patch.read_text(), agents.read_text())

        assert cmd_setup(args) == 0

        assert (patch.read_text(), agents.read_text()) == first

    def test_json_mode_is_machine_readable(self, harness_home, capsys):
        cmd_setup(argparse.Namespace(
            client=["dsh"], write=False, no_cli=False, dsh_profile=None, json=True, list_clients=False
        ))

        payload = json.loads(capsys.readouterr().out)
        assert payload["written"] is False
        assert payload["clients"][0]["client"] == "dsh"
        assert payload["clients"][0]["command"][-1] == "serve"

    def test_an_unknown_client_exits_nonzero_instead_of_pretending(self, harness_home, capsys):
        code = cmd_setup(argparse.Namespace(
            client=["vscodium"], write=True, no_cli=False, dsh_profile=None, json=True, list_clients=False
        ))

        assert code == 1
        assert "vscodium" in capsys.readouterr().out

    def test_list_needs_no_home_and_writes_nothing(self, harness_home, capsys):
        assert cmd_setup(argparse.Namespace(list_clients=True, json=False)) == 0
        out = capsys.readouterr().out
        for name in ("claude-code", "dsh", "zed", "generic"):
            assert name in out


class TestCmdDoctor:
    """`doctor` answers the question `check` cannot: is it actually being used?"""

    @pytest.fixture
    def harness_home(self, monkeypatch, tmp_path):
        home = tmp_path / "dsh"
        (home / "profiles" / "web").mkdir(parents=True)
        (home / "profiles" / "web" / "cordis.yml").write_text("[]\n")
        monkeypatch.setenv("DSH_HOME", str(home))
        # Path.home() reads $HOME, so this keeps `scan` off the developer's real
        # ~/.claude.json — otherwise every doctor assertion depends on their machine.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setattr(cli_clients.shutil, "which", lambda _n: None)
        return home

    def _args(self, **over):
        base = {"days": 30, "strict": False, "no_verify": True, "dsh_profile": None, "json": False}
        base.update(over)
        return argparse.Namespace(**base)

    def _seed_usage(self, db, rows) -> None:
        import sqlite3

        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT INTO search_access_log (file_path, tool, query, tokens_returned, "
            "tokens_baseline, client, accessed_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            rows,
        )
        conn.commit()
        conn.close()

    def test_uninitialized_database_is_a_problem(self, monkeypatch, tmp_path, harness_home, capsys):
        _use_sqlite_db(monkeypatch, tmp_path / "never.db")

        code = cmd_doctor(self._args())

        assert code == 1
        assert "problem:" in capsys.readouterr().out

    def test_wired_but_never_called_warns_without_failing(self, monkeypatch, tmp_path, harness_home, capsys):
        """A machine that installed gnosis five minutes ago is in exactly this state."""
        _use_sqlite_db(monkeypatch, tmp_path / "fresh.db")
        cmd_init_db(argparse.Namespace(dry_run=False))
        cmd_setup(argparse.Namespace(
            client=["dsh"], write=True, no_cli=False, dsh_profile=None, json=False, list_clients=False
        ))
        capsys.readouterr()

        assert cmd_doctor(self._args()) == 0
        assert "no call has ever been logged" in capsys.readouterr().out

    def test_strict_turns_never_called_into_a_failure(self, monkeypatch, tmp_path, harness_home):
        """For a CI job that wants to assert real usage, not just wiring."""
        _use_sqlite_db(monkeypatch, tmp_path / "strict.db")
        cmd_init_db(argparse.Namespace(dry_run=False))
        cmd_setup(argparse.Namespace(
            client=["dsh"], write=True, no_cli=False, dsh_profile=None, json=False, list_clients=False
        ))

        assert cmd_doctor(self._args(strict=True)) == 1

    def test_a_real_call_is_reported_as_live_wiring(self, monkeypatch, tmp_path, harness_home, capsys):
        db = tmp_path / "used.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        cmd_setup(argparse.Namespace(
            client=["dsh"], write=True, no_cli=False, dsh_profile=None, json=False, list_clients=False
        ))
        self._seed_usage(db, [("docs/a.md", "search_docs", "q", 10, 900, "dsh-mcp-client/0.0.1")])
        capsys.readouterr()

        assert cmd_doctor(self._args()) == 0
        out = capsys.readouterr().out
        assert "dsh-mcp-client/0.0.1" in out
        assert "the wiring is live" in out

    def test_json_mode_carries_the_usage_rows(self, monkeypatch, tmp_path, harness_home, capsys):
        db = tmp_path / "used-json.db"
        _use_sqlite_db(monkeypatch, db)
        cmd_init_db(argparse.Namespace(dry_run=False))
        self._seed_usage(db, [("docs/a.md", "search_docs", "q", 10, 900, "claude-code/2.1.0")])

        assert cmd_doctor(self._args(json=True)) == 0

        payload = json.loads(capsys.readouterr().out)
        assert [row["client"] for row in payload["usage"]] == ["claude-code/2.1.0"]
        assert payload["server"]["command"][-1] == "serve"
