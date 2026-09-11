"""Tests for REST API endpoints."""

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from starlette.testclient import TestClient

from gnosis_mcp.config import GnosisMcpConfig

# The MCP transport-security allow-list covers loopback hosts only; a TestClient
# with the default "testserver" Host is rejected with HTTP 421 before it ever
# reaches a handler. Both the base URL and the CORS origin below stay inside it.
_LOOPBACK_BASE_URL = "http://127.0.0.1:8000"
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}

_INITIALIZE_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "rest-test", "version": "1.0"},
}


@pytest.fixture
def rest_client(monkeypatch, tmp_path):
    """Create a test client for the REST app with a fresh SQLite DB."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GNOSIS_MCP_REST", "true")

    config = GnosisMcpConfig.from_env()

    from gnosis_mcp.rest import create_rest_app

    app = create_rest_app(config)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def seeded_client(monkeypatch, tmp_path):
    """REST client with a document pre-inserted."""
    from gnosis_mcp.backend import create_backend
    from gnosis_mcp.rest import create_rest_app

    db_path = str(tmp_path / "seeded.db")
    monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GNOSIS_MCP_REST", "true")

    config = GnosisMcpConfig.from_env()

    async def _seed():
        backend = create_backend(config)
        await backend.startup()
        await backend.init_schema()
        await backend.upsert_doc(
            "guides/quickstart.md",
            ["Getting started with Gnosis MCP documentation server."],
            title="Quickstart Guide",
            category="guides",
        )
        await backend.shutdown()

    asyncio.run(_seed())

    app = create_rest_app(config)
    with TestClient(app) as client:
        yield client


class TestHealth:
    def test_health_ok(self, rest_client):
        r = rest_client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestSearchEndpoint:
    def test_search_requires_query(self, rest_client):
        r = rest_client.get("/api/search")
        assert r.status_code == 400

    def test_search_returns_results(self, seeded_client):
        r = seeded_client.get("/api/search?q=quickstart")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert len(data["results"]) >= 1
        assert data["results"][0]["file_path"] == "guides/quickstart.md"

    def test_search_with_limit(self, seeded_client):
        r = seeded_client.get("/api/search?q=gnosis&limit=1")
        assert r.status_code == 200
        assert len(r.json()["results"]) <= 1

    def test_search_with_category(self, seeded_client):
        r = seeded_client.get("/api/search?q=quickstart&category=guides")
        assert r.status_code == 200
        assert len(r.json()["results"]) >= 1

    def test_search_no_results(self, seeded_client):
        r = seeded_client.get("/api/search?q=zzzznonexistent")
        assert r.status_code == 200
        assert r.json()["results"] == []


class TestDocEndpoint:
    def test_get_doc(self, seeded_client):
        r = seeded_client.get("/api/docs/guides/quickstart.md")
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Quickstart Guide"
        assert "content" in data

    def test_get_doc_not_found(self, seeded_client):
        r = seeded_client.get("/api/docs/nonexistent.md")
        assert r.status_code == 404


class TestRelatedEndpoint:
    def test_get_related_empty(self, seeded_client):
        r = seeded_client.get("/api/docs/guides/quickstart.md/related")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_get_related_not_found(self, seeded_client):
        r = seeded_client.get("/api/docs/nonexistent.md/related")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert isinstance(data["results"], list)


class TestCategoriesEndpoint:
    def test_list_categories(self, seeded_client):
        r = seeded_client.get("/api/categories")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert any(c["category"] == "guides" for c in data)


class TestApiKeyAuth:
    def test_rejects_without_key(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "auth.db")
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_REST", "true")
        monkeypatch.setenv("GNOSIS_MCP_API_KEY", "sk-secret")
        config = GnosisMcpConfig.from_env()

        from gnosis_mcp.rest import create_rest_app

        with TestClient(create_rest_app(config)) as client:
            # /api/* is gated; /health is intentionally public (see ApiKeyMiddleware).
            r = client.get("/api/categories")
            assert r.status_code == 401
            r_health = client.get("/health")
            assert r_health.status_code == 200, "/health must bypass auth for monitoring"

    def test_accepts_with_key(self, monkeypatch, tmp_path):
        import asyncio

        from gnosis_mcp.sqlite_backend import SqliteBackend

        db_path = str(tmp_path / "auth.db")
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_REST", "true")
        monkeypatch.setenv("GNOSIS_MCP_API_KEY", "sk-secret")
        config = GnosisMcpConfig.from_env()

        async def _init() -> None:
            be = SqliteBackend(config)
            await be.startup()
            await be.init_schema()
            await be.shutdown()

        asyncio.run(_init())

        from gnosis_mcp.rest import create_rest_app

        with TestClient(create_rest_app(config)) as client:
            r = client.get("/api/categories", headers={"Authorization": "Bearer sk-secret"})
            assert r.status_code == 200


class TestContextEndpoint:
    def test_context_empty(self, seeded_client):
        r = seeded_client.get("/api/context")
        assert r.status_code == 200
        data = r.json()
        assert "docs" in data
        assert "stats" in data

    def test_context_with_topic(self, seeded_client):
        r = seeded_client.get("/api/context?topic=quickstart")
        assert r.status_code == 200
        data = r.json()
        assert "docs" in data

    def test_context_topic_auto_embeds(self, monkeypatch, tmp_path):
        """A natural-language topic is embedded, not handed to keyword search."""
        import gnosis_mcp.embed as embed_mod
        from gnosis_mcp.backend import create_backend
        from gnosis_mcp.rest import create_rest_app
        from gnosis_mcp.sqlite_backend import SqliteBackend

        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", str(tmp_path / "topic-embed.db"))
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_REST", "true")

        config = GnosisMcpConfig.from_env()
        object.__setattr__(config, "embed_provider", "local")

        # The REST lifespan starts the backend but never creates the schema —
        # that is `init-db`'s job in production, and the seeding step here.
        async def _init_schema():
            backend = create_backend(config)
            await backend.startup()
            await backend.init_schema()
            await backend.shutdown()

        asyncio.run(_init_schema())

        calls = {}

        async def _spy_search(self, query, **kwargs):
            calls["query"] = query
            calls.update(kwargs)
            return []

        def _fake_embed(texts, **kwargs):
            calls["embedded"] = texts
            return [[0.1, 0.2, 0.3]]

        monkeypatch.setattr(SqliteBackend, "search", _spy_search)
        monkeypatch.setattr(embed_mod, "embed_texts", _fake_embed)

        topic = "how does the file watcher re-ingest changed files"
        with TestClient(create_rest_app(config)) as client:
            r = client.get("/api/context", params={"topic": topic})

        assert r.status_code == 200
        assert calls["embedded"] == [topic]
        assert calls["query_embedding"] == [0.1, 0.2, 0.3]

    def test_context_with_limit(self, seeded_client):
        r = seeded_client.get("/api/context?limit=1")
        assert r.status_code == 200
        assert len(r.json()["docs"]) <= 1


def _seed_docs(config: GnosisMcpConfig, docs: list[tuple[str, list[str], str, str]]) -> None:
    """Create the schema and insert `(path, chunks, title, category)` documents."""
    from gnosis_mcp.backend import create_backend

    async def _seed() -> None:
        backend = create_backend(config)
        await backend.startup()
        await backend.init_schema()
        for path, chunks, title, category in docs:
            await backend.upsert_doc(path, chunks, title=title, category=category)
        await backend.shutdown()

    asyncio.run(_seed())


def _sse_payload(response) -> dict:
    """Decode the JSON-RPC message out of an SSE or JSON MCP response."""
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    return json.loads(response.text)


def _mcp_call(
    client,
    method: str,
    *,
    params: dict | None = None,
    session_id: str | None = None,
    origin: str | None = None,
):
    headers = dict(_MCP_HEADERS)
    if session_id:
        headers["mcp-session-id"] = session_id
    if origin:
        headers["Origin"] = origin
    if method == "initialize" and params is None:
        params = _INITIALIZE_PARAMS
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=headers,
    )


@contextlib.contextmanager
def _combined_app_client(monkeypatch, tmp_path, *, cors_origins: str | None = None):
    """TestClient over the real combined MCP+REST app on a seeded SQLite DB."""
    from gnosis_mcp.rest import create_combined_app
    from gnosis_mcp.server import mcp as mcp_server

    monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", str(tmp_path / "combined.db"))
    monkeypatch.setenv("GNOSIS_MCP_BACKEND", "sqlite")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GNOSIS_MCP_REST", "true")
    if cors_origins:
        monkeypatch.setenv("GNOSIS_MCP_CORS_ORIGINS", cors_origins)
    else:
        monkeypatch.delenv("GNOSIS_MCP_CORS_ORIGINS", raising=False)

    config = GnosisMcpConfig.from_env()
    _seed_docs(
        config,
        [
            (
                "guides/quickstart.md",
                ["Getting started with the Gnosis MCP documentation server."],
                "Quickstart Guide",
                "guides",
            )
        ],
    )

    # FastMCP caches its StreamableHTTPSessionManager on the module-level server,
    # and the SDK allows `run()` to be entered only once per instance — so each
    # test that drives the combined lifespan needs a fresh manager.
    monkeypatch.setattr(mcp_server, "_session_manager", None)
    app = create_combined_app(mcp_server, "streamable-http", config)
    with TestClient(app, base_url=_LOOPBACK_BASE_URL) as client:
        yield client


@pytest.fixture
def combined_client(monkeypatch, tmp_path):
    """Combined MCP+REST app: the same ASGI app `serve --rest` hands to uvicorn."""
    with _combined_app_client(monkeypatch, tmp_path) as client:
        yield client


class TestCombinedApp:
    def test_create_combined_app(self, monkeypatch, tmp_path):
        """Verify combined app mounts both MCP and REST."""
        with _combined_app_client(monkeypatch, tmp_path) as client:
            # REST health endpoint works
            r = client.get("/health")
            assert r.status_code == 200

            # REST search endpoint works
            r = client.get("/api/search?q=quickstart")
            assert r.status_code == 200
            assert r.json()["results"][0]["file_path"] == "guides/quickstart.md"

    def test_mcp_initialize_and_tools_list_share_the_port(self, combined_client):
        """Regression: `POST /mcp` returned 500 under `--rest`.

        Starlette never enters a mounted sub-application's lifespan, and FastMCP
        creates the streamable-HTTP session task group there, so every MCP
        request died with "Task group is not initialized. Make sure to use run()"
        once `create_combined_app` mounted the transport. Reproduced against a
        real server before the fix: GET /health 200, POST /mcp 500.
        """
        init = _mcp_call(combined_client, "initialize")
        assert init.status_code == 200, init.text
        result = _sse_payload(init)["result"]
        assert result["serverInfo"]["name"] == "gnosis-mcp"
        session_id = init.headers.get("mcp-session-id")
        assert session_id, "initialize must hand back a session id"

        tools = _mcp_call(combined_client, "tools/list", session_id=session_id)
        assert tools.status_code == 200, tools.text
        names = {t["name"] for t in _sse_payload(tools)["result"]["tools"]}
        assert {"search_docs", "get_doc", "get_related"}.issubset(names), names

        # REST keeps working on the same port, same app.
        assert combined_client.get("/health").status_code == 200

    def test_mcp_tool_call_runs_alongside_rest(self, combined_client):
        """A real MCP tool call and a REST call see the same seeded database."""
        init = _mcp_call(combined_client, "initialize")
        session_id = init.headers["mcp-session-id"]
        call = _mcp_call(
            combined_client,
            "tools/call",
            params={"name": "search_docs", "arguments": {"query": "quickstart"}},
            session_id=session_id,
        )
        assert call.status_code == 200, call.text
        mcp_results = json.loads(_sse_payload(call)["result"]["content"][0]["text"])
        assert mcp_results[0]["file_path"] == "guides/quickstart.md"

        rest_results = combined_client.get("/api/search?q=quickstart").json()["results"]
        assert rest_results[0]["file_path"] == "guides/quickstart.md"

    def test_cors_headers_reach_rest_and_mcp(self, monkeypatch, tmp_path):
        """The CORS wrapper must not be what breaks (or is skipped by) MCP."""
        origin = _LOOPBACK_BASE_URL
        with _combined_app_client(monkeypatch, tmp_path, cors_origins=origin) as client:
            health = client.get("/health", headers={"Origin": origin})
            assert health.status_code == 200
            assert health.headers["access-control-allow-origin"] == origin

            init = _mcp_call(client, "initialize", origin=origin)
            assert init.status_code == 200
            assert init.headers["access-control-allow-origin"] == origin

            preflight = client.options(
                "/api/search",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert preflight.status_code == 204
            assert preflight.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"


class TestGraphStatsEndpoint:
    def test_graph_stats_empty(self, seeded_client):
        resp = seeded_client.get("/api/graph/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data


class TestEmbedEndpoint:
    """POST /v1/embed — OpenAI-shaped embeddings endpoint."""

    def test_embed_400_when_body_missing(self, rest_client):
        # Use empty payload that is valid JSON but missing texts
        r = rest_client.post("/v1/embed", json={})
        assert r.status_code == 400
        assert "texts" in r.json()["error"]

    def test_embed_400_when_texts_not_list(self, rest_client):
        r = rest_client.post("/v1/embed", json={"texts": "hello"})
        assert r.status_code == 400

    def test_embed_400_when_texts_empty(self, rest_client):
        r = rest_client.post("/v1/embed", json={"texts": []})
        assert r.status_code == 400

    def test_embed_400_when_text_too_large(self, rest_client):
        huge = "a" * 60_000
        r = rest_client.post("/v1/embed", json={"texts": [huge]})
        assert r.status_code == 400

    def test_embed_400_when_model_not_string(self, rest_client):
        r = rest_client.post("/v1/embed", json={"texts": ["hi"], "model": 42})
        assert r.status_code == 400

    def test_embed_400_when_too_many_texts(self, rest_client):
        r = rest_client.post("/v1/embed", json={"texts": ["x"] * 300})
        assert r.status_code == 400

    def test_embed_503_when_no_embed_extra(self, rest_client, monkeypatch):
        # Simulate ImportError by removing gnosis_mcp.embed from sys.modules and
        # forcing the import to fail.
        import sys
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "gnosis_mcp.embed":
                raise ImportError("simulated missing extra")
            return original_import(name, *args, **kwargs)

        # Clear cached module so the patched import is used.
        sys.modules.pop("gnosis_mcp.embed", None)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        r = rest_client.post("/v1/embed", json={"texts": ["hello"]})
        assert r.status_code == 503
        assert "embeddings extra" in r.json()["error"]

    def test_embed_503_when_provider_raises(self, rest_client, monkeypatch):
        # Patch embed_texts to raise — covers the broad except branch.
        from gnosis_mcp import embed as embed_mod

        def boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(embed_mod, "embed_texts", boom)
        r = rest_client.post("/v1/embed", json={"texts": ["hello"]})
        assert r.status_code == 503
        assert "embedding failed" in r.json()["error"]

    def test_embed_success_returns_openai_shape(self, rest_client, monkeypatch):
        # Stub embed_texts to return fixed vectors → no model download in tests.
        from gnosis_mcp import embed as embed_mod

        def fake_embed(texts, **kwargs):
            return [[0.1, 0.2, 0.3] for _ in texts]

        monkeypatch.setattr(embed_mod, "embed_texts", fake_embed)
        r = rest_client.post("/v1/embed", json={"texts": ["hello", "world"]})
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {"model", "dim", "vectors", "usage"}
        assert data["dim"] == 3
        assert len(data["vectors"]) == 2
        assert data["vectors"][0] == [0.1, 0.2, 0.3]
        assert data["usage"]["prompt_tokens"] > 0

    def test_embed_honors_model_override(self, rest_client, monkeypatch):
        from gnosis_mcp import embed as embed_mod

        captured = {}

        def fake_embed(texts, **kwargs):
            captured["model"] = kwargs.get("model")
            return [[0.0]] * len(texts)

        monkeypatch.setattr(embed_mod, "embed_texts", fake_embed)
        r = rest_client.post(
            "/v1/embed",
            json={"texts": ["hi"], "model": "intfloat/multilingual-e5-large"},
        )
        assert r.status_code == 200
        assert captured["model"] == "intfloat/multilingual-e5-large"
        assert r.json()["model"] == "intfloat/multilingual-e5-large"


# ---------------------------------------------------------------------------
# End-to-end: one real port, one real uvicorn process, MCP + REST together
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — loopback only
        return resp.status, resp.read().decode()


def _wait_for_health(url: str, timeout: float = 30.0) -> int:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return _get(url)[0]
        except Exception as exc:  # server still booting
            last_error = exc
            time.sleep(0.25)
    raise AssertionError(f"server never became healthy at {url}: {last_error}")


@pytest.mark.e2e
def test_rest_and_mcp_coexist_on_one_real_port(tmp_path):
    """`serve --rest --transport streamable-http`: MCP and REST on one port.

    The full-scale reproduction of the defect: a real uvicorn process, a real
    MCP client doing initialize + tools/list over HTTP, and real REST calls on
    the same port. Before the fix this server answered GET /health with 200 and
    POST /mcp with 500 ("Task group is not initialized. Make sure to use run()").
    """
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    db = tmp_path / "combined-e2e.db"
    env = os.environ.copy()
    env.update(
        {
            "GNOSIS_MCP_DATABASE_URL": str(db),
            "GNOSIS_MCP_BACKEND": "sqlite",
            "GNOSIS_MCP_LOG_LEVEL": "WARNING",
            "GNOSIS_MCP_CORS_ORIGINS": "*",
        }
    )

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "widgets.md").write_text(
        "---\ncategory: guides\n---\n\n"
        "# Widget Guide\n\n"
        "Widgets describe a pipeline stage in the gnosis-mcp documentation "
        "server. This paragraph exists so the file survives the minimum chunk "
        "size check that ingest applies to every document.\n\n"
        "## Installing widgets\n\n"
        "Install a widget with your package manager, then run the widget doctor "
        "command against your documentation corpus to confirm it is reachable.\n"
    )

    for args in (["init-db"], ["ingest", str(docs)]):
        done = subprocess.run(
            [sys.executable, "-m", "gnosis_mcp", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert done.returncode == 0, f"{args} failed: {done.stderr}"

    port = _free_port()
    log_path = tmp_path / "server.log"
    with log_path.open("w") as log_file:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gnosis_mcp",
                "serve",
                "--rest",
                "--transport",
                "streamable-http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            assert _wait_for_health(f"{base}/health") == 200

            # REST routes on the same port
            status, body = _get(f"{base}/api/search?q=widget")
            assert status == 200
            assert json.loads(body)["results"][0]["file_path"] == "widgets.md"

            status, body = _get(f"{base}/api/categories")
            assert status == 200
            assert json.loads(body)[0]["category"] == "guides"

            # MCP transport on the same port, driven by the real SDK client
            async def _drive_mcp() -> list[str]:
                async with streamablehttp_client(f"{base}/mcp") as (read, write, _):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        assert init.serverInfo.name == "gnosis-mcp"
                        tools = await session.list_tools()
                        names = [t.name for t in tools.tools]
                        result = await session.call_tool("search_docs", {"query": "widget"})
                        hits = json.loads(result.content[0].text)
                        assert hits[0]["file_path"] == "widgets.md"
                        return names

            names = asyncio.run(_drive_mcp())
            assert {"search_docs", "get_doc", "get_related"}.issubset(set(names)), names
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover — hung shutdown
                proc.kill()
                proc.wait(timeout=15)

    server_log = log_path.read_text()
    assert "Task group is not initialized" not in server_log, server_log
    assert "Traceback" not in server_log, server_log
