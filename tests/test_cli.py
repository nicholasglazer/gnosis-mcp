"""Tests for CLI utilities."""

import sys

import pytest

from ansuz.cli import _mask_url, main


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


class TestMainNoArgs:
    def test_no_command_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ansuz"])
        with pytest.raises(SystemExit, match="1"):
            main()

    def test_version_flag(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["ansuz", "--version"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert "ansuz 0.1.0" in out
