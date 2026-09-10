"""Client wiring: make an install reproducible, and prove it gets used.

Installing the package is half an installation. The other half is a client that
knows where the binary is and an agent that chooses to call it — and both halves
fail silently. A config naming a path that does not exist on *this* machine
produces a client that starts happily with zero tools, and a perfectly wired
client still produces zero retrievals if the agent never reaches for it.

Nobody has one client. The same person runs Claude Code on one machine, a
harness on another, and an editor that speaks MCP on a third, so a DSH-only or
Claude-only installer is the thing that would need rewriting next month. This
module is therefore a **registry**: every client is one :class:`Client` row
declaring where its server entry goes, where its always-loaded instructions go,
and the vendor command that owns the format. Behaviour lives in
:func:`configure` and reads that table, so supporting a new client is a data
change with a test, not a new branch in four places.

Three strategies, tried in order, because no single one is universal:

* ``cli``  — the vendor's own `mcp add`. Preferred: they keep their schema
  current, and we never guess at a format we cannot exercise.
* ``file`` — a marker-delimited managed block, or a JSON merge. Works when
  there is no CLI, and never reorders or reformats what the user already has.
* ``print`` — the snippet and the exact path. The fallback that makes this
  work for *any* client, including one that did not exist when this shipped.

Everything here is pure and backend-free on purpose: `setup` runs before
`init-db` exists, and `doctor` must still report wiring when the database is
unreachable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - invoking the client's own documented CLI
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = [
    "CLIENTS",
    "Env",
    "YAML_BEGIN",
    "YAML_END",
    "MD_BEGIN",
    "MD_END",
    "client_names",
    "client_present",
    "configure",
    "detect_env",
    "detected_clients",
    "dsh_profile_name",
    "render_agents_rule",
    "render_dsh_block",
    "render_stdio_json",
    "resolve_command",
    "scan",
    "server_entry",
    "verify_dsh",
    "write_managed_text",
]

SERVER_NAME = "gnosis"

YAML_BEGIN = "# >>> gnosis-mcp — managed block; `gnosis-mcp setup --write` rewrites it"
YAML_END = "# <<< gnosis-mcp"
MD_BEGIN = "<!-- >>> gnosis-mcp — managed block; `gnosis-mcp setup --write` rewrites it -->"
MD_END = "<!-- <<< gnosis-mcp -->"

AGENTS_RULE = f"""\
## {SERVER_NAME}-mcp knowledge base

This machine indexes its own documentation in gnosis-mcp, mounted here as the
`mcp__{SERVER_NAME}__*` tools. Reach for them before grepping whenever the
question is about *documented* knowledge — curated guides, runbooks, past
decisions, vendor references:

- `mcp__{SERVER_NAME}__get_context` first when you want orientation or don't
  know the corpus's shape (omit the topic for the most-accessed documents).
- `mcp__{SERVER_NAME}__search_docs` for a specific question. Results carry the
  document path, so follow up precisely instead of reading broadly.
- `mcp__{SERVER_NAME}__get_doc` once you know which document matters.

It is usually faster than reading files, and it is the only place some of that
knowledge exists.\
"""


@dataclass(frozen=True)
class Env:
    """Everything path resolution depends on, injected so tests need no real home.

    The XDG/APPDATA roots are resolved once in :func:`detect_env` rather than
    read from ``os.environ`` at lookup time, which keeps every path decision a
    pure function of the value the caller passed in.
    """

    home: Path
    cwd: Path
    dsh_home: Path
    config_home: Path
    appdata_home: Path
    dsh_profile: str | None = None
    platform: str = "linux"

    def xdg(self, *parts: str) -> Path:
        """`$XDG_CONFIG_HOME`-aware path, matching how these clients resolve it."""
        return self.config_home.joinpath(*parts)

    def appdata(self, *parts: str) -> Path:
        return self.appdata_home.joinpath(*parts)


def detect_env(*, dsh_profile: str | None = None, cwd: Path | None = None) -> Env:
    """Build the real :class:`Env` for this machine."""
    home = Path.home()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    appdata = os.environ.get("APPDATA")
    return Env(
        home=home,
        cwd=cwd or Path.cwd(),
        dsh_home=Path(os.environ.get("DSH_HOME") or (home / ".dsh")),
        config_home=Path(xdg) if xdg else home / ".config",
        appdata_home=Path(appdata) if appdata else home / "AppData" / "Roaming",
        dsh_profile=dsh_profile,
        platform=sys.platform,
    )


def _dsh_profile_dir(env: Env) -> Path | None:
    """The profile whose patch layer should carry the row.

    Explicit `--dsh-profile` wins. Otherwise prefer ``web`` — the GUI profile,
    and the one whose sessions a user actually talks to — then accept a lone
    profile directory. Ambiguity returns None so the caller asks rather than
    guesses: writing into the wrong profile is invisible, because the profile
    the user boots simply keeps not having the tools.
    """
    root = env.dsh_home / "profiles"
    if env.dsh_profile:
        candidate = root / env.dsh_profile
        return candidate if candidate.is_dir() else None
    web = root / "web"
    if web.is_dir():
        return web
    if not root.is_dir():
        return None
    candidates = sorted(p for p in root.iterdir() if p.is_dir() and (p / "cordis.yml").exists())
    return candidates[0] if len(candidates) == 1 else None


def _vscode_user_mcp(env: Env) -> Path:
    """VS Code's per-user `mcp.json`, which differs by platform."""
    if env.platform.startswith("darwin"):
        return env.home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    if env.platform.startswith("win"):
        return env.appdata("Code", "User", "mcp.json")
    return env.xdg("Code", "User", "mcp.json")


def _cline_settings(env: Env) -> Path:
    """Cline keeps its MCP settings in the extension's VS Code global storage."""
    if env.platform.startswith("darwin"):
        return (
            env.home
            / "Library"
            / "Application Support"
            / "Code"
            / "User"
            / "globalStorage"
            / "saoudrizwan.claude-dev"
            / "settings"
            / "cline_mcp_settings.json"
        )
    if env.platform.startswith("win"):
        return env.appdata(
            "Code",
            "User",
            "globalStorage",
            "saoudrizwan.claude-dev",
            "settings",
            "cline_mcp_settings.json",
        )
    return env.xdg(
        "Code",
        "User",
        "globalStorage",
        "saoudrizwan.claude-dev",
        "settings",
        "cline_mcp_settings.json",
    )


@dataclass(frozen=True)
class Client:
    """One MCP client, described rather than implemented.

    ``rules`` is the field that matters most and is easiest to get wrong: it is
    the file the client loads into *every* session. It is ``None`` exactly when
    the client forwards the server's own MCP ``instructions`` field, which
    already carries the "prefer me over reading files" preamble — writing a
    second copy there would bill the user for the same paragraph twice.
    """

    name: str
    label: str
    kind: str  # "json" | "yaml-patch" | "print"
    config: Callable[[Env], Path] | None = None
    key: str = "mcpServers"
    shape: str = "flat"  # "flat" (command/args) | "zed" (command.path/args)
    add_cli: tuple[str, ...] | None = None
    rules: Callable[[Env], Path] | None = None
    snippet_format: str = "json"
    docs: str = ""
    verified: bool = False
    note: str = ""


def _dsh_config(env: Env) -> Path:
    directory = _dsh_profile_dir(env)
    if directory is None:
        raise ValueError(
            "cannot tell which DeepSeek Harness profile to patch; pass --dsh-profile "
            f"(looked under {env.dsh_home / 'profiles'})"
        )
    return directory / "cordis.patch.yml"


# The registry. Order is the order `setup` reports, so it reads as "the common
# ones first". `verified` marks the surfaces this repository can actually
# exercise in CI or has exercised by hand; an unverified row still gets a
# correct snippet, it just does not claim to have been run.
CLIENTS: tuple[Client, ...] = (
    Client(
        name="claude-code",
        label="Claude Code",
        kind="json",
        config=lambda env: env.home / ".claude.json",
        add_cli=("claude", "mcp", "add-json", "--scope", "user", SERVER_NAME),
        docs="https://docs.claude.com/en/docs/claude-code/mcp",
        verified=True,
        note="Reads the server's MCP `instructions`, so no rule file is needed.",
    ),
    Client(
        name="dsh",
        label="DeepSeek Harness",
        kind="yaml-patch",
        config=_dsh_config,
        rules=lambda env: env.dsh_home / "AGENTS.md",
        snippet_format="yaml",
        docs="https://github.com/deepseek-ai/dsh",
        verified=True,
        note="Mounts at the profile layer, so every session and every preset gets it.",
    ),
    Client(
        name="codex",
        label="OpenAI Codex CLI",
        kind="print",
        config=lambda env: env.home / ".codex" / "config.toml",
        add_cli=("codex", "mcp", "add", SERVER_NAME, "--"),
        rules=lambda env: env.home / ".codex" / "AGENTS.md",
        snippet_format="toml",
        docs="https://developers.openai.com/codex/config-reference",
        note="`codex mcp add` owns config.toml; the snippet is the manual equivalent.",
    ),
    Client(
        name="gemini-cli",
        label="Gemini CLI",
        kind="json",
        config=lambda env: env.home / ".gemini" / "settings.json",
        add_cli=("gemini", "mcp", "add", SERVER_NAME),
        rules=lambda env: env.home / ".gemini" / "GEMINI.md",
        docs="https://github.com/google-gemini/gemini-cli",
    ),
    Client(
        name="cursor",
        label="Cursor",
        kind="json",
        config=lambda env: env.home / ".cursor" / "mcp.json",
        rules=lambda env: env.cwd / ".cursor" / "rules" / "gnosis.mdc",
        docs="https://docs.cursor.com/context/model-context-protocol",
        verified=True,
    ),
    Client(
        name="vscode",
        label="VS Code (Copilot)",
        kind="json",
        config=_vscode_user_mcp,
        key="servers",
        docs="https://code.visualstudio.com/docs/copilot/chat/mcp-servers",
        verified=True,
        note="VS Code names the map `servers`; every other client here uses `mcpServers`.",
    ),
    Client(
        name="windsurf",
        label="Windsurf",
        kind="json",
        config=lambda env: env.home / ".codeium" / "windsurf" / "mcp_config.json",
        docs="https://docs.windsurf.com/windsurf/cascade/mcp",
    ),
    Client(
        name="cline",
        label="Cline (VS Code extension)",
        kind="json",
        config=_cline_settings,
        docs="https://docs.cline.bot/mcp/configuring-mcp-servers",
        note="Lives in VS Code global storage; quit VS Code before editing it.",
    ),
    Client(
        name="zed",
        label="Zed",
        kind="print",
        config=lambda env: env.xdg("zed", "settings.json"),
        key="context_servers",
        shape="zed",
        docs="https://zed.dev/docs/assistant/context-servers",
        note="settings.json is JSONC, so gnosis will not rewrite it — paste the block.",
    ),
    Client(
        name="generic",
        label="Any other MCP client",
        kind="print",
        snippet_format="json",
        docs="",
        note="A stdio server entry; the path is absolute so any working directory works.",
    ),
)

_BY_NAME = {client.name: client for client in CLIENTS}


def client_names() -> list[str]:
    """Registry order, for `--help` and for validating `--client`."""
    return [client.name for client in CLIENTS]


def resolve_command() -> list[str]:
    """Build the argv a client should run, valid on the machine running this.

    Prefers the console script on ``PATH`` because that is what a package
    manager (pip, pipx, `uv tool install`) created and what survives an upgrade.
    Falls back to the *current* interpreter with ``-m``, which is the only
    correct answer when gnosis-mcp is imported from an environment whose `bin`
    directory is not on ``PATH`` — a project venv, a container, an Arch package.

    The path is absolute in both cases: an MCP client usually spawns servers
    from a different working directory and a different `PATH` than the shell
    that ran the install, so a bare ``gnosis-mcp`` is a coin flip.

    A `PATH` entry outside the running interpreter's own `bin` directory wins.
    Package managers run the console script *from inside* the venv they created,
    with that venv's `bin` prepended, so a plain lookup returns the private copy
    — correct, but an implementation detail of the package manager. The stable
    entry point a user's shell resolves (``~/.local/bin/gnosis-mcp``,
    ``/usr/bin/gnosis-mcp``) is the one to write into a config file.

    Paths are made absolute with `os.path.abspath`, never `Path.resolve`: the
    console script is usually a symlink into a versioned directory
    (``~/.local/share/uv/tools/gnosis-mcp/bin/...``), and following it would
    write the disposable target into the user's config instead of the stable
    name that points at it.
    """
    own_bin = Path(sys.executable).parent
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory or Path(directory) == own_bin:
            continue
        candidate = Path(directory) / "gnosis-mcp"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return [os.path.abspath(candidate), "serve"]

    exe = shutil.which("gnosis-mcp")
    if exe:
        return [os.path.abspath(exe), "serve"]
    return [sys.executable, "-m", "gnosis_mcp", "serve"]


def server_entry(command: list[str], *, shape: str = "flat") -> dict[str, object]:
    """The stdio server description, in the shape the target client expects.

    Zed nests the launch command under ``command``; everyone else takes a flat
    ``command``/``args`` pair. This is the one place that difference lives.
    """
    if shape == "zed":
        return {"command": {"path": command[0], "args": list(command[1:]), "env": {}}}
    return {"command": command[0], "args": list(command[1:])}


def render_stdio_json(command: list[str], *, key: str = "mcpServers", shape: str = "flat") -> str:
    """A paste-ready JSON block for any client that takes a `mcpServers`-style map."""
    return json.dumps({key: {SERVER_NAME: server_entry(command, shape=shape)}}, indent=2)


def render_stdio_toml(command: list[str]) -> str:
    """The Codex `config.toml` equivalent, for when `codex` is not on PATH."""
    args = ", ".join(json.dumps(a) for a in command[1:])
    return f"[mcp_servers.{SERVER_NAME}]\ncommand = {json.dumps(command[0])}\nargs = [{args}]\n"


def _yaml_str(value: str) -> str:
    """Quote a scalar for YAML using JSON quoting, which YAML accepts verbatim.

    Windows paths (``C:\\\\Users\\\\...``) and any path containing ``:`` need this;
    leaving them bare is how a config silently becomes a parse error, or worse,
    a different string.
    """
    return json.dumps(value, ensure_ascii=False)


def render_dsh_block(command: list[str]) -> str:
    """The DeepSeek Harness patch-layer row that mounts gnosis in every session.

    Mounted at the profile layer rather than in an agent preset on purpose: a
    preset is chosen per session and sessions on a shipped preset cannot be
    edited at all, so anything less means "gnosis is available in some
    sessions", which is not a property an agent can rely on.
    """
    lines = [
        YAML_BEGIN,
        f"# Tools arrive as `mcp__{SERVER_NAME}__*` in every session on every preset.",
        "# failOnStartupError keeps the harness booting if this path later breaks —",
        "# the tools then fail on call instead of taking every session down with them.",
        "- insert:",
        f"    - id: mcp-{SERVER_NAME}",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        f"        serverName: {SERVER_NAME}",
        "        transport: stdio",
        f"        command: {_yaml_str(command[0])}",
        f"        args: [{', '.join(_yaml_str(a) for a in command[1:])}]",
        "        failOnStartupError: false",
        YAML_END,
    ]
    return "\n".join(lines) + "\n"


def render_agents_rule() -> str:
    """The instruction that turns "mounted" into "used" in the DeepSeek Harness.

    The harness registers an MCP server's tools and discards its `instructions`
    field — ``dsh-mcp-client`` never reads it — so the server's own "prefer me
    over reading files" preamble reaches Claude Code but *not* DSH. Without a
    rule in ``$DSH_HOME/AGENTS.md``, the one instruction file the harness loads
    into every session, a correctly mounted gnosis is a set of tools the agent
    has no reason to prefer. This block is that reason, and it is the whole
    difference between installed and used.
    """
    return f"{MD_BEGIN}\n\n{AGENTS_RULE}\n{MD_END}\n"


def _render_mdc_rule() -> str:
    """Cursor's rule format: MDC is markdown with a frontmatter block."""
    return (
        f"---\ndescription: gnosis-mcp knowledge base\nalwaysApply: true\n---\n\n{AGENTS_RULE}\n"
    )


def _rule_text(client: Client) -> str:
    return (
        _render_mdc_rule() if client.name == "cursor" else f"{MD_BEGIN}\n{AGENTS_RULE}\n{MD_END}\n"
    )


def write_managed_text(path: Path, block: str, begin: str = MD_BEGIN, end: str = MD_END) -> str:
    """Insert or replace one marker-delimited block. Returns what it did.

    One of ``created`` / ``appended`` / ``updated`` / ``unchanged``. Text outside
    the markers is never touched, which is what makes this safe against a
    hand-maintained file: the alternative — parsing and re-serialising it —
    would silently drop the user's comments and ordering.
    """
    original = path.read_text(encoding="utf-8") if path.exists() else None

    if original is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, block)
        return "created"

    start, stop = original.find(begin), original.find(end)
    if start != -1 and stop > start:
        updated = original[:start] + block.rstrip("\n") + original[stop + len(end) :]
        if updated == original:
            return "unchanged"
        _atomic_write(path, updated)
        return "updated"

    # Append only. Exactly one blank line between the user's last line and ours,
    # whatever they did or did not leave at the end of the file.
    if not original or original.endswith("\n\n"):
        separator = ""
    elif original.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    _atomic_write(path, original + separator + block)
    return "appended"


def merge_json_server(path: Path, command: list[str], *, key: str, shape: str = "flat") -> str:
    """Add or refresh one server inside a strict-JSON config. Returns the action.

    A real JSON round-trip rather than a text block, because these files are
    objects: appending text to one produces invalid JSON and takes every other
    server in the file down with it. Python dicts keep insertion order, and the
    dump matches how these clients write the file themselves, so the user's own
    entries survive byte-for-byte in practice.
    """
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                f"{path} is not valid JSON ({exc}); add the server by hand or fix the file first"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path} does not contain a JSON object; add the server by hand")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}

    servers = data.get(key)
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise ValueError(f"{path} has a non-object `{key}`; add the server by hand")

    entry = server_entry(command, shape=shape)
    existed = SERVER_NAME in servers
    if existed and servers[SERVER_NAME] == entry:
        return "unchanged"
    servers[SERVER_NAME] = entry
    data[key] = servers
    _atomic_write(path, json.dumps(data, indent=2) + "\n")
    return "updated" if existed else "created"


def _atomic_write(path: Path, text: str) -> None:
    """Replace a config file in one step.

    A half-written client config is worse than no config: the client fails to
    parse it and the user loses every other server in the same file. The temp
    file is a sibling so ``os.replace`` stays on one filesystem and is atomic.
    """
    tmp = path.with_name(path.name + ".gnosis-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _run_add_cli(client: Client, command: list[str]) -> dict[str, object]:
    """Hand the install to the vendor's own CLI when it is installed.

    Their format, their validation, their version. We only build the argument
    list, and we report the exact command we ran so a failure is reproducible
    by hand instead of being a mystery inside our exit code.
    """
    add_cli = client.add_cli
    if add_cli is None:  # pragma: no cover - callers check first
        return {"available": False, "argv": []}
    argv = list(add_cli)
    if client.name == "claude-code":
        # `claude mcp add-json <name> <json>` takes the entry as one argument,
        # which sidesteps its per-flag parsing of args and env.
        argv.append(json.dumps({SERVER_NAME: server_entry(command)}))
    elif client.name == "codex":
        argv.extend(command)
    elif client.name == "gemini-cli":
        argv.append("--")
        argv.extend(command)

    if shutil.which(add_cli[0]) is None:
        return {"available": False, "argv": argv}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": True, "argv": argv, "ok": False, "detail": str(exc)}
    return {
        "available": True,
        "argv": argv,
        "ok": proc.returncode == 0,
        "detail": (proc.stderr or proc.stdout or "").strip()[-400:],
    }


def configure(
    name: str,
    *,
    write: bool = False,
    command: list[str] | None = None,
    env: Env | None = None,
    use_cli: bool = True,
) -> dict[str, object]:
    """Render — and with ``write``, apply — the wiring for one client.

    Returns a report rather than raising, because "this client is not installed
    here" is a normal outcome of asking for several at once and the caller needs
    to print it. An unusable *request* (unknown client, DSH profile that cannot
    be located, a config file that is not valid JSON) raises ``ValueError``.
    """
    client = _BY_NAME.get(name)
    if client is None:
        raise ValueError(f"unknown client {name!r}; choose from {', '.join(client_names())}")
    env = env or detect_env()
    command = command or resolve_command()

    report: dict[str, object] = {
        "client": client.name,
        "label": client.label,
        "command": command,
        "kind": client.kind,
        "note": client.note,
        "docs": client.docs,
        "verified": client.verified,
        "wrote": False,
        "rules_path": None,
    }
    report["snippet"] = {
        "toml": render_stdio_toml,
        "json": lambda cmd: render_stdio_json(cmd, key=client.key, shape=client.shape),
        "yaml": render_dsh_block,
    }[client.snippet_format](command)
    if client.config is not None:
        report["path"] = str(client.config(env))

    if not write:
        if client.add_cli is not None:
            report["add_cli"] = list(client.add_cli)
        return report

    # ---- Writes below here. Prefer the vendor CLI, then the file, and report
    # ---- exactly what happened rather than a success the user cannot observe.

    installed = False
    if client.kind == "yaml-patch":
        path = client.config(env)  # type: ignore[misc]
        stale = _unmanaged_row(path, command)
        if stale:
            # Appending here would leave two rows carrying `id: mcp-gnosis` in
            # one patch array, and the loader's behaviour on a duplicate id is
            # not a thing to discover in production. Refuse and say exactly what
            # to delete instead.
            report["warning"] = stale
            report["action"] = "skipped"
            return report
        report["action"] = write_managed_text(
            path, render_dsh_block(command), YAML_BEGIN, YAML_END
        )
        installed = True
    elif client.add_cli and use_cli:
        cli = _run_add_cli(client, command)
        report["cli"] = cli
        if cli.get("available") and cli.get("ok"):
            report["action"] = "cli"
            installed = True
        elif cli.get("available"):
            # Installed but refused: do not silently write a second copy the
            # vendor's own tooling would then disagree with.
            report["action"] = "cli-failed"
            return report
        # Not on PATH — fall through to the file strategy.
    if not installed and client.kind == "json" and client.config is not None:
        report["action"] = merge_json_server(
            client.config(env), command, key=client.key, shape=client.shape
        )
        installed = True

    report["wrote"] = installed

    # The rule is written only once the server entry actually exists. Writing it
    # first would tell the agent to prefer `mcp__gnosis__*` tools that the client
    # has never heard of — worse than saying nothing, because the agent would
    # then trust a capability it does not have.
    if installed and client.rules is not None:
        rule = client.rules(env)
        report["rules_path"] = str(rule)
        report["rules_action"] = write_managed_text(rule, _rule_text(client))
    return report


def _unmanaged_row(path: Path, command: list[str]) -> str | None:
    """Detect a hand-written gnosis row that predates the managed block.

    Anyone who wired this up from an earlier README has a `- id: mcp-gnosis`
    entry with no markers around it. Appending a second one produces a patch
    array with a duplicate id, so the right move is to stop and hand the user a
    one-line fix rather than to guess which of the two the loader keeps.
    """
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if YAML_BEGIN in text:
        return None
    if "mcp-gnosis" not in text and "mcp_gnosis" not in text:
        return None
    return (
        f"{path} already contains a hand-written gnosis row without the managed "
        "markers. Delete that row and re-run, so `setup` can own it from here."
    )


def scan(*, env: Env | None = None) -> list[dict[str, object]]:
    """Report which clients are wired *on this machine*, writing nothing.

    Presence is decided by searching the file for the server name, not by
    parsing it. That is deliberate: this runs against files the project does not
    own — a JSONC editor config, a YAML file with `!!js` expressions, a config
    too malformed to load — and a parse failure there would surface as "not
    configured", which is the one conclusion a diagnostic must not guess at.
    The authoritative check is the client actually calling the server, which is
    what the access log answers.
    """
    env = env or detect_env()
    results: list[dict[str, object]] = []
    for client in CLIENTS:
        if client.config is None:
            continue
        try:
            path = client.config(env)
        except ValueError as exc:
            results.append({"client": client.name, "label": client.label, "error": str(exc)})
            continue
        configured = False
        if path.is_file():
            try:
                configured = SERVER_NAME in path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                configured = False
        results.append(
            {
                "client": client.name,
                "label": client.label,
                "path": str(path),
                "exists": path.is_file(),
                "configured": configured,
            }
        )
    return results


def client_present(client: Client, env: Env, *, use_cli: bool = True) -> bool:
    """Whether this client plausibly exists on this machine.

    Deliberately shallow, and deliberately not "is the config file present":
    ``~/.claude.json`` lives directly in ``$HOME``, which exists on every
    machine, so a parent-directory test would claim Claude Code is installed
    everywhere. A false positive costs one extra line of setup output; a false
    negative hides a client the user then has to name by hand, so the test is
    generous within that bound — an existing config, a real vendor directory,
    or the vendor's own CLI on `PATH`.
    """
    if client.config is not None:
        try:
            path = client.config(env)
        except ValueError:
            path = None
        if path is not None:
            if path.exists():
                return True
            if path.parent != env.home and path.parent.is_dir():
                return True
    return bool(
        use_cli
        and client.add_cli is not None
        and client.add_cli[0]
        and shutil.which(client.add_cli[0])
    )


def detected_clients(env: Env | None = None, *, use_cli: bool = True) -> list[str]:
    """Registry names for the clients worth offering to wire up here."""
    env = env or detect_env()
    return [
        client.name
        for client in CLIENTS
        if client.name != "generic" and client_present(client, env, use_cli=use_cli)
    ]


def dsh_profile_name(env: Env | None = None) -> str | None:
    """The DeepSeek Harness profile name `--dump-config` wants."""
    directory = _dsh_profile_dir(env or detect_env())
    return directory.name if directory else None


def verify_dsh(env: Env | None = None, *, timeout: int = 120) -> dict[str, object]:
    """Ask the harness itself whether the composed profile still validates.

    ``dsh --dump-config`` composes every layer — bundle, profile, patch — and
    refuses to print a tree it cannot load. That is the only check that actually
    proves the row we appended is loadable: a YAML syntax check would happily
    pass a row whose plugin name does not resolve or whose config the plugin
    rejects, which is the realistic way this breaks after the user upgrades the
    harness or the repo is renamed. Skipped, not failed, when the launcher is
    not on `PATH`.
    """
    env = env or detect_env()
    profile = dsh_profile_name(env)
    if profile is None:
        return {"checked": False, "detail": "no DeepSeek Harness profile found"}
    if shutil.which("dsh") is None:
        return {"checked": False, "detail": "dsh launcher not on PATH"}
    argv = ["dsh", "--profile", profile, "--dump-config"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        return {"checked": False, "detail": f"could not run dsh: {exc}"}
    ok = proc.returncode == 0
    detail = "composition validates" if ok else (proc.stderr or proc.stdout or "").strip()[-400:]
    return {"checked": True, "ok": ok, "argv": argv, "detail": detail}
