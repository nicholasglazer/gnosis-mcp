"""Tests for client wiring: renderers, managed blocks, and the registry.

No database, no real home directory, and no vendor CLI is ever executed — an
autouse fixture removes `shutil.which` results so a stray `configure(...,
write=True)` cannot reach the developer's own `~/.claude.json`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gnosis_mcp import clients
from gnosis_mcp.clients import (
    CLIENTS,
    MD_BEGIN,
    MD_END,
    YAML_BEGIN,
    YAML_END,
    Env,
    client_names,
    client_present,
    configure,
    detected_clients,
    dsh_profile_name,
    merge_json_server,
    render_agents_rule,
    render_dsh_block,
    render_stdio_json,
    render_stdio_toml,
    resolve_command,
    scan,
    server_entry,
    verify_dsh,
    write_managed_text,
)


@pytest.fixture(autouse=True)
def no_vendor_cli(monkeypatch, tmp_path):
    """Never let a test find a real client binary — or a real gnosis-mcp — on PATH.

    `_run_add_cli` shells out to the vendor's own command, which writes to the
    user's real config rather than the temp `Env`, so the one thing a test must
    not do is let it run. `resolve_command` reads PATH directly as well, and the
    developer's actual install must not leak into an assertion.
    """
    monkeypatch.setattr(clients.shutil, "which", lambda _name: None)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


@pytest.fixture
def env(tmp_path):
    """An Env whose every path lands inside tmp_path."""
    dsh = tmp_path / ".dsh"
    (dsh / "profiles" / "web").mkdir(parents=True)
    (dsh / "profiles" / "web" / "cordis.yml").write_text("[]\n")
    return Env(
        home=tmp_path,
        cwd=tmp_path / "project",
        dsh_home=dsh,
        config_home=tmp_path / ".config",
        appdata_home=tmp_path / "AppData",
    )


class TestRegistry:
    def test_names_are_unique_and_ordered(self):
        names = client_names()
        assert len(names) == len(set(names))
        assert names[0] == "claude-code" and names[-1] == "generic"

    def test_every_client_declares_a_usable_kind(self):
        for client in CLIENTS:
            assert client.kind in {"json", "yaml-patch", "print"}, client.name
            assert client.snippet_format in {"json", "toml", "yaml"}, client.name
            if client.kind in {"json", "yaml-patch"}:
                assert client.config is not None, f"{client.name} cannot be written without a path"

    def test_json_clients_use_a_key_their_client_actually_reads(self):
        keys = {c.name: c.key for c in CLIENTS}
        assert keys["vscode"] == "servers"
        assert keys["zed"] == "context_servers"
        assert keys["claude-code"] == "mcpServers"

    def test_only_clients_that_skip_mcp_instructions_get_a_rule_file(self):
        """A rule file is a duplicate of the server's `instructions` — or a stand-in.

        Claude Code forwards the MCP `instructions` field, so a rule would bill
        the user for the same paragraph twice. The harness discards it, so
        without the rule the tools are mounted and never preferred.
        """
        rules = {c.name: c.rules is not None for c in CLIENTS}
        assert rules["claude-code"] is False
        assert rules["dsh"] is True
        assert rules["codex"] is True


class TestResolveCommand:
    def test_prefers_the_console_script_and_makes_it_absolute(self, monkeypatch, tmp_path):
        script = tmp_path / "bin" / "gnosis-mcp"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", str(script.parent))
        monkeypatch.setattr(clients.shutil, "which", lambda _n: str(script))

        assert resolve_command() == [str(script), "serve"]

    def test_skips_a_copy_inside_the_running_interpreters_own_bin(self, monkeypatch, tmp_path):
        """`uv tool run` prepends its venv bin, so a naive lookup finds a private copy."""
        private = tmp_path / "venv" / "bin"
        public = tmp_path / "local" / "bin"
        for directory in (private, public):
            directory.mkdir(parents=True)
            candidate = directory / "gnosis-mcp"
            candidate.write_text("#!/bin/sh\n")
            candidate.chmod(0o755)
        monkeypatch.setattr(clients.sys, "executable", str(private / "python3"))
        monkeypatch.setenv("PATH", f"{private}{os.pathsep}{public}")
        monkeypatch.setattr(clients.shutil, "which", lambda _n: str(private / "gnosis-mcp"))

        assert resolve_command() == [str(public / "gnosis-mcp"), "serve"]

    def test_does_not_follow_a_shim_into_the_package_managers_private_directory(self, monkeypatch, tmp_path):
        """The console script is usually a symlink; the config should name the link."""
        shim_dir = tmp_path / "local" / "bin"
        private = tmp_path / "uv" / "tools" / "gnosis-mcp" / "bin"
        for directory in (shim_dir, private):
            directory.mkdir(parents=True)
        target = private / "gnosis-mcp"
        target.write_text("#!/bin/sh\n")
        target.chmod(0o755)
        shim = shim_dir / "gnosis-mcp"
        shim.symlink_to(target)
        monkeypatch.setenv("PATH", str(shim_dir))
        monkeypatch.setattr(clients.shutil, "which", lambda _n: str(shim))

        assert resolve_command() == [str(shim), "serve"]

    def test_falls_back_to_the_running_interpreter(self):
        """The only correct answer when no console script is on PATH."""
        assert resolve_command() == [sys.executable, "-m", "gnosis_mcp", "serve"]


class TestRenderers:
    def test_flat_entry_is_command_and_args(self):
        assert server_entry(["/bin/gnosis-mcp", "serve"]) == {
            "command": "/bin/gnosis-mcp",
            "args": ["serve"],
        }

    def test_zed_nests_the_command(self):
        entry = server_entry(["/bin/gnosis-mcp", "serve"], shape="zed")
        assert entry == {"command": {"path": "/bin/gnosis-mcp", "args": ["serve"], "env": {}}}

    def test_json_uses_the_key_it_was_given(self):
        flat = json.loads(render_stdio_json(["/bin/g", "serve"]))
        vscode = json.loads(render_stdio_json(["/bin/g", "serve"], key="servers"))
        assert list(flat) == ["mcpServers"]
        assert list(vscode) == ["servers"]
        assert flat["mcpServers"]["gnosis"]["args"] == ["serve"]

    def test_toml_snippet_is_a_codex_table(self):
        toml = render_stdio_toml(["/bin/g", "serve"])
        assert toml.startswith("[mcp_servers.gnosis]")
        assert 'command = "/bin/g"' in toml
        assert 'args = ["serve"]' in toml

    def test_dsh_block_quotes_paths_yaml_would_mangle(self):
        """A bare Windows path is a parse error or, worse, a different string."""
        block = render_dsh_block([r"C:\Program Files\gnosis-mcp.exe", "serve"])

        assert r'command: "C:\\Program Files\\gnosis-mcp.exe"' in block
        assert block.startswith(YAML_BEGIN)
        assert block.rstrip().endswith(YAML_END)
        assert "- insert:" in block
        assert "serverName: gnosis" in block
        # The row must survive a broken binary rather than take every session down.
        assert "failOnStartupError: false" in block

    def test_agents_rule_names_the_three_tools_it_wants_used(self):
        rule = render_agents_rule()
        assert rule.startswith(MD_BEGIN) and rule.rstrip().endswith(MD_END)
        for tool in ("get_context", "search_docs", "get_doc"):
            assert f"mcp__gnosis__{tool}" in rule


class TestWriteManagedText:
    def test_creates_a_missing_file_and_its_parents(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "file.yml"

        assert write_managed_text(path, "BLOCK\n", YAML_BEGIN, YAML_END) == "created"
        assert path.read_text() == "BLOCK\n"

    def test_appends_without_touching_what_is_already_there(self, tmp_path):
        path = tmp_path / "file.yml"
        path.write_text("# the user's own careful comments\n- id: theirs\n")

        assert write_managed_text(path, "BLOCK\n", YAML_BEGIN, YAML_END) == "appended"
        text = path.read_text()
        assert text.startswith("# the user's own careful comments\n- id: theirs\n")
        assert text.endswith("BLOCK\n")
        assert "\n\nBLOCK" in text

    def test_rerunning_replaces_in_place_instead_of_appending_twice(self, tmp_path):
        """The property that makes `setup` safe to run after every upgrade."""
        path = tmp_path / "file.yml"
        path.write_text("- id: theirs\n")
        write_managed_text(path, f"{YAML_BEGIN}\nfirst\n{YAML_END}\n", YAML_BEGIN, YAML_END)

        assert write_managed_text(path, f"{YAML_BEGIN}\nsecond\n{YAML_END}\n", YAML_BEGIN, YAML_END) == "updated"
        text = path.read_text()
        assert text.count(YAML_BEGIN) == 1
        assert "second" in text and "first" not in text
        assert "- id: theirs" in text

    def test_identical_rewrite_reports_unchanged_and_leaves_mtime_alone(self, tmp_path):
        path = tmp_path / "file.yml"
        block = f"{YAML_BEGIN}\nbody\n{YAML_END}\n"
        write_managed_text(path, block, YAML_BEGIN, YAML_END)
        before = path.stat().st_mtime_ns

        assert write_managed_text(path, block, YAML_BEGIN, YAML_END) == "unchanged"
        assert path.stat().st_mtime_ns == before

    def test_an_unterminated_block_is_appended_rather_than_eaten(self, tmp_path):
        """A half-deleted marker must not cause the rest of the file to vanish."""
        path = tmp_path / "file.yml"
        path.write_text(f"- id: theirs\n{YAML_BEGIN}\nhalf a block\n")

        assert write_managed_text(path, "BLOCK\n", YAML_BEGIN, YAML_END) == "appended"
        assert "- id: theirs" in path.read_text()


class TestMergeJsonServer:
    def test_creates_a_config_and_keeps_sibling_servers(self, tmp_path):
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "other"}}}))

        assert merge_json_server(path, ["/bin/g", "serve"], key="mcpServers") == "created"
        data = json.loads(path.read_text())
        assert data["mcpServers"]["other"] == {"command": "other"}
        assert data["mcpServers"]["gnosis"]["command"] == "/bin/g"

    def test_preserves_unrelated_top_level_keys(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"theme": "dark", "mcpServers": {}}))

        merge_json_server(path, ["/bin/g", "serve"], key="mcpServers")

        assert json.loads(path.read_text())["theme"] == "dark"

    def test_is_idempotent(self, tmp_path):
        path = tmp_path / "mcp.json"
        merge_json_server(path, ["/bin/g", "serve"], key="mcpServers")
        before = path.read_text()

        assert merge_json_server(path, ["/bin/g", "serve"], key="mcpServers") == "unchanged"
        assert path.read_text() == before

    def test_updates_a_stale_command_path(self, tmp_path):
        """The realistic upgrade: the binary moved, the config did not."""
        path = tmp_path / "mcp.json"
        merge_json_server(path, ["/old/g", "serve"], key="mcpServers")

        assert merge_json_server(path, ["/new/g", "serve"], key="mcpServers") == "updated"
        assert json.loads(path.read_text())["mcpServers"]["gnosis"]["command"] == "/new/g"

    def test_refuses_to_destroy_a_file_it_cannot_parse(self, tmp_path):
        path = tmp_path / "mcp.json"
        path.write_text("{ this is not json")

        with pytest.raises(ValueError, match="not valid JSON"):
            merge_json_server(path, ["/bin/g", "serve"], key="mcpServers")
        assert path.read_text() == "{ this is not json"


class TestConfigure:
    def test_unknown_client_is_a_hard_error(self, env):
        with pytest.raises(ValueError, match="unknown client"):
            configure("vscodium", env=env)

    def test_preview_writes_nothing(self, env):
        report = configure("dsh", env=env)

        assert report["wrote"] is False
        assert not (env.dsh_home / "profiles" / "web" / "cordis.patch.yml").exists()
        assert not (env.dsh_home / "AGENTS.md").exists()

    def test_dsh_writes_both_the_mount_and_the_rule_that_uses_it(self, env):
        """Mounting alone is the silent failure: tools present, never preferred."""
        report = configure("dsh", write=True, env=env)

        patch = env.dsh_home / "profiles" / "web" / "cordis.patch.yml"
        agents = env.dsh_home / "AGENTS.md"
        assert report["wrote"] is True
        assert "mcp-gnosis" in patch.read_text()
        assert "mcp__gnosis__search_docs" in agents.read_text()
        assert report["rules_action"] == "created"

    def test_dsh_is_idempotent_across_runs(self, env):
        configure("dsh", write=True, env=env)
        patch = env.dsh_home / "profiles" / "web" / "cordis.patch.yml"
        agents = env.dsh_home / "AGENTS.md"
        first = (patch.read_text(), agents.read_text())

        second = configure("dsh", write=True, env=env)

        assert (patch.read_text(), agents.read_text()) == first
        assert second["action"] == "unchanged"

    def test_dsh_reports_the_unusable_request_when_no_profile_exists(self, tmp_path):
        bare = Env(
            home=tmp_path,
            cwd=tmp_path,
            dsh_home=tmp_path / "nothing-here",
            config_home=tmp_path / ".config",
            appdata_home=tmp_path / "AppData",
        )

        with pytest.raises(ValueError, match="dsh-profile"):
            configure("dsh", write=True, env=bare)

    def test_print_only_client_never_writes_an_orphan_rule(self, env):
        """A rule naming tools the client does not have is worse than silence.

        Zed's settings.json is JSONC, so gnosis refuses to rewrite it — and must
        then also refuse to write the instruction that assumes it did.
        """
        report = configure("zed", write=True, env=env)

        assert report["wrote"] is False
        assert report["snippet"]
        assert not (env.cwd / ".cursor" / "rules" / "gnosis.mdc").exists()

    def test_json_client_lands_in_a_temp_home_not_the_real_one(self, env):
        report = configure("vscode", write=True, env=env, command=["/bin/gnosis-mcp", "serve"])

        target = env.xdg("Code", "User", "mcp.json")
        assert report["wrote"] is True
        assert json.loads(target.read_text())["servers"]["gnosis"]["args"] == ["serve"]

    def test_a_failing_vendor_cli_is_reported_not_worked_around(self, env, monkeypatch):
        """If `claude` exists and refuses, do not silently write a rival config."""
        monkeypatch.setattr(clients.shutil, "which", lambda n: "/usr/bin/claude" if n == "claude" else None)
        monkeypatch.setattr(
            clients.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 2, "", "no such scope"),
        )

        report = configure("claude-code", write=True, env=env)

        assert report["action"] == "cli-failed"
        assert report["wrote"] is False
        assert not (env.home / ".claude.json").exists()


class TestDshProfileSelection:
    def test_explicit_profile_wins(self, env):
        (env.dsh_home / "profiles" / "headless").mkdir()

        assert dsh_profile_name(Env(**{**env.__dict__, "dsh_profile": "headless"})) == "headless"

    def test_web_is_preferred_when_present(self, env):
        assert dsh_profile_name(env) == "web"

    def test_a_lone_profile_is_accepted(self, tmp_path):
        dsh = tmp_path / ".dsh"
        for name in ("web",):
            (dsh / "profiles" / name).mkdir(parents=True)
        (dsh / "profiles" / "web" / "cordis.yml").write_text("[]\n")
        env = Env(
            home=tmp_path,
            cwd=tmp_path,
            dsh_home=dsh,
            config_home=tmp_path / ".config",
            appdata_home=tmp_path / "AppData",
        )

        assert dsh_profile_name(env) == "web"

    def test_ambiguity_returns_none_rather_than_guessing(self, tmp_path):
        """Patching the wrong profile is invisible — that profile just lacks tools."""
        dsh = tmp_path / ".dsh"
        for name in ("alpha", "beta"):
            (dsh / "profiles" / name).mkdir(parents=True)
            (dsh / "profiles" / name / "cordis.yml").write_text("[]\n")
        env = Env(
            home=tmp_path,
            cwd=tmp_path,
            dsh_home=dsh,
            config_home=tmp_path / ".config",
            appdata_home=tmp_path / "AppData",
        )

        assert dsh_profile_name(env) is None


class TestScanAndDetect:
    def test_scan_marks_a_configured_client(self, env):
        (env.home / ".cursor").mkdir()
        (env.home / ".cursor" / "mcp.json").write_text('{"mcpServers": {"gnosis": {}}}')

        rows = {row["client"]: row for row in scan(env=env)}

        assert rows["cursor"]["configured"] is True
        assert rows["dsh"]["configured"] is False

    def test_scan_does_not_parse_so_a_broken_file_is_not_a_false_negative(self, env):
        """JSONC, `!!js`, or plain corruption must not read as "not configured"."""
        (env.home / ".cursor").mkdir()
        (env.home / ".cursor" / "mcp.json").write_text('{ // comments\n "gnosis": 1 }')

        rows = {row["client"]: row for row in scan(env=env)}

        assert rows["cursor"]["configured"] is True

    def test_home_directory_alone_does_not_imply_claude_code(self, env):
        """`~/.claude.json` sits in $HOME, which exists everywhere."""
        assert client_present(clients._BY_NAME["claude-code"], env) is False

    def test_a_real_claude_config_is_detected(self, env):
        (env.home / ".claude.json").write_text("{}")

        assert client_present(clients._BY_NAME["claude-code"], env) is True

    def test_detected_clients_excludes_the_generic_fallback(self, env):
        (env.home / ".claude.json").write_text("{}")

        names = detected_clients(env)

        assert "claude-code" in names
        assert "generic" not in names


class TestVerifyDsh:
    def test_skipped_when_the_launcher_is_absent(self, env):
        assert verify_dsh(env) == {"checked": False, "detail": "dsh launcher not on PATH"}

    def test_reports_the_harness_verdict(self, env, monkeypatch):
        monkeypatch.setattr(clients.shutil, "which", lambda _n: "/usr/bin/dsh")
        monkeypatch.setattr(
            clients.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "tree", "")
        )

        result = verify_dsh(env)

        assert result["checked"] is True and result["ok"] is True
        assert result["argv"] == ["dsh", "--profile", "web", "--dump-config"]

    def test_a_rejected_composition_keeps_the_reason(self, env, monkeypatch):
        monkeypatch.setattr(clients.shutil, "which", lambda _n: "/usr/bin/dsh")
        monkeypatch.setattr(
            clients.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "unknown plugin id"),
        )

        result = verify_dsh(env)

        assert result["checked"] is True and result["ok"] is False
        assert "unknown plugin id" in str(result["detail"])


class TestUnmanagedRowGuard:
    """An older README told people to paste the row by hand; that row has no markers."""

    def _handwritten(self, env) -> Path:
        patch = env.dsh_home / "profiles" / "web" / "cordis.patch.yml"
        patch.write_text(
            "# my own notes\n"
            "- insert:\n"
            "    - id: mcp-gnosis\n"
            "      name: '@deepseek-ai/dsh-mcp-client'\n"
        )
        return patch

    def test_setup_refuses_instead_of_duplicating_the_id(self, env):
        patch = self._handwritten(env)
        before = patch.read_text()

        report = configure("dsh", write=True, env=env)

        assert report["wrote"] is False
        assert report["action"] == "skipped"
        assert "Delete that row" in str(report["warning"])
        assert patch.read_text() == before

    def test_a_managed_block_is_still_updated_normally(self, env):
        """The guard must not fire on our own output."""
        configure("dsh", write=True, env=env)

        assert configure("dsh", write=True, env=env)["action"] == "unchanged"

    def test_an_unrelated_file_is_untouched(self, env):
        patch = env.dsh_home / "profiles" / "web" / "cordis.patch.yml"
        patch.write_text("# nothing about gnosis here\n")

        assert configure("dsh", write=True, env=env)["wrote"] is True
