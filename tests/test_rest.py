"""Tests for REST API endpoints."""

import asyncio

import pytest
from starlette.testclient import TestClient

from gnosis_mcp.config import GnosisMcpConfig


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

    def test_context_with_limit(self, seeded_client):
        r = seeded_client.get("/api/context?limit=1")
        assert r.status_code == 200
        assert len(r.json()["docs"]) <= 1


class TestCombinedApp:
    def test_create_combined_app(self, monkeypatch, tmp_path):
        """Verify combined app mounts both MCP and REST."""
        from gnosis_mcp.backend import create_backend
        from gnosis_mcp.rest import create_combined_app
        from gnosis_mcp.server import mcp

        db_path = str(tmp_path / "combined.db")
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_REST", "true")
        config = GnosisMcpConfig.from_env()

        # Initialize schema first so search doesn't fail with missing tables
        async def _init():
            backend = create_backend(config)
            await backend.startup()
            await backend.init_schema()
            await backend.shutdown()

        asyncio.run(_init())

        app = create_combined_app(mcp, "streamable-http", config)
        with TestClient(app) as client:
            # REST health endpoint works
            r = client.get("/health")
            assert r.status_code == 200

            # REST search endpoint works (empty results since no docs)
            r = client.get("/api/search?q=test")
            assert r.status_code == 200


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
