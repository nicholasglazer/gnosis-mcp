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
            r = client.get("/health")
            assert r.status_code == 401

    def test_accepts_with_key(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "auth.db")
        monkeypatch.setenv("GNOSIS_MCP_DATABASE_URL", db_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("GNOSIS_MCP_REST", "true")
        monkeypatch.setenv("GNOSIS_MCP_API_KEY", "sk-secret")
        config = GnosisMcpConfig.from_env()

        from gnosis_mcp.rest import create_rest_app

        with TestClient(create_rest_app(config)) as client:
            r = client.get("/health", headers={"Authorization": "Bearer sk-secret"})
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
