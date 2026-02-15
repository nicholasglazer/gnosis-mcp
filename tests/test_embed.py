"""Tests for embedding provider abstraction (no API calls required)."""

import json
import urllib.request

import pytest

from gnosis_mcp.embed import (
    _build_request_ollama,
    _build_request_openai,
    _parse_response_ollama,
    _parse_response_openai,
    embed_texts,
    get_provider_url,
)


class TestGetProviderUrl:
    def test_openai_default(self):
        assert get_provider_url("openai") == "https://api.openai.com/v1/embeddings"

    def test_ollama_default(self):
        assert get_provider_url("ollama") == "http://localhost:11434/api/embed"

    def test_custom_url_overrides(self):
        url = "https://my-server.com/embed"
        assert get_provider_url("openai", url) == url
        assert get_provider_url("ollama", url) == url
        assert get_provider_url("custom", url) == url

    def test_custom_without_url_raises(self):
        with pytest.raises(ValueError, match="No default URL"):
            get_provider_url("custom")

    def test_unknown_provider_without_url_raises(self):
        with pytest.raises(ValueError, match="No default URL"):
            get_provider_url("unknown")


class TestBuildRequestOpenai:
    def test_payload_format(self):
        req = _build_request_openai(
            ["hello", "world"], "text-embedding-3-small", "sk-test", "https://api.openai.com/v1/embeddings"
        )
        payload = json.loads(req.data)
        assert payload["input"] == ["hello", "world"]
        assert payload["model"] == "text-embedding-3-small"

    def test_auth_header(self):
        req = _build_request_openai(
            ["text"], "model", "sk-abc123", "https://api.openai.com/v1/embeddings"
        )
        assert req.get_header("Authorization") == "Bearer sk-abc123"

    def test_no_auth_header_when_no_key(self):
        req = _build_request_openai(
            ["text"], "model", None, "https://api.openai.com/v1/embeddings"
        )
        assert req.get_header("Authorization") is None

    def test_content_type(self):
        req = _build_request_openai(
            ["text"], "model", None, "https://api.openai.com/v1/embeddings"
        )
        assert req.get_header("Content-type") == "application/json"

    def test_method_is_post(self):
        req = _build_request_openai(
            ["text"], "model", None, "https://api.openai.com/v1/embeddings"
        )
        assert req.method == "POST"


class TestBuildRequestOllama:
    def test_payload_format(self):
        req = _build_request_ollama(
            ["hello", "world"], "nomic-embed-text", "http://localhost:11434/api/embed"
        )
        payload = json.loads(req.data)
        assert payload["model"] == "nomic-embed-text"
        assert payload["input"] == ["hello", "world"]

    def test_no_auth_header(self):
        req = _build_request_ollama(
            ["text"], "model", "http://localhost:11434/api/embed"
        )
        assert req.get_header("Authorization") is None

    def test_content_type(self):
        req = _build_request_ollama(
            ["text"], "model", "http://localhost:11434/api/embed"
        )
        assert req.get_header("Content-type") == "application/json"


class TestParseResponseOpenai:
    def test_standard_format(self):
        data = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3], "index": 0},
                {"embedding": [0.4, 0.5, 0.6], "index": 1},
            ]
        }
        result = _parse_response_openai(data)
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    def test_single_embedding(self):
        data = {"data": [{"embedding": [1.0, 2.0]}]}
        result = _parse_response_openai(data)
        assert result == [[1.0, 2.0]]

    def test_empty_data(self):
        data = {"data": []}
        result = _parse_response_openai(data)
        assert result == []


class TestParseResponseOllama:
    def test_standard_format(self):
        data = {"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
        result = _parse_response_ollama(data)
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    def test_single_embedding(self):
        data = {"embeddings": [[1.0, 2.0]]}
        result = _parse_response_ollama(data)
        assert result == [[1.0, 2.0]]

    def test_empty_embeddings(self):
        data = {"embeddings": []}
        result = _parse_response_ollama(data)
        assert result == []


class TestEmbedTexts:
    def test_empty_texts_returns_empty(self):
        result = embed_texts([], "openai")
        assert result == []

    def test_openai_request_format(self, monkeypatch):
        """Verify embed_texts sends correct request to OpenAI."""
        captured = {}

        def mock_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data)
            captured["headers"] = dict(req.headers)

            class MockResponse:
                def read(self):
                    return json.dumps({
                        "data": [{"embedding": [0.1, 0.2], "index": 0}]
                    }).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = embed_texts(["test text"], "openai", "text-embedding-3-small", "sk-key")
        assert result == [[0.1, 0.2]]
        assert captured["url"] == "https://api.openai.com/v1/embeddings"
        assert captured["payload"]["input"] == ["test text"]
        assert captured["payload"]["model"] == "text-embedding-3-small"

    def test_ollama_request_format(self, monkeypatch):
        """Verify embed_texts sends correct request to Ollama."""
        captured = {}

        def mock_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data)

            class MockResponse:
                def read(self):
                    return json.dumps({
                        "embeddings": [[0.3, 0.4]]
                    }).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = embed_texts(["test"], "ollama", "nomic-embed-text")
        assert result == [[0.3, 0.4]]
        assert captured["url"] == "http://localhost:11434/api/embed"
        assert captured["payload"]["model"] == "nomic-embed-text"

    def test_custom_provider_uses_openai_format(self, monkeypatch):
        """Custom provider uses OpenAI-compatible request/response format."""
        captured = {}

        def mock_urlopen(req, timeout=None):
            captured["url"] = req.full_url

            class MockResponse:
                def read(self):
                    return json.dumps({
                        "data": [{"embedding": [0.5, 0.6], "index": 0}]
                    }).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = embed_texts(
            ["test"], "custom", "my-model", url="https://custom.api/embed"
        )
        assert result == [[0.5, 0.6]]
        assert captured["url"] == "https://custom.api/embed"

    def test_http_error_propagates(self, monkeypatch):
        """HTTP errors from the provider should propagate to the caller."""

        def mock_urlopen(req, timeout=None):
            raise urllib.request.URLError("Connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        with pytest.raises(urllib.request.URLError, match="Connection refused"):
            embed_texts(["test"], "openai", "model", "key")

    def test_multiple_texts_batch(self, monkeypatch):
        """Verify multiple texts are sent in a single batch."""

        def mock_urlopen(req, timeout=None):
            payload = json.loads(req.data)
            n = len(payload["input"])

            class MockResponse:
                def read(self):
                    return json.dumps({
                        "data": [
                            {"embedding": [float(i)], "index": i}
                            for i in range(n)
                        ]
                    }).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = embed_texts(["a", "b", "c"], "openai", "model", "key")
        assert len(result) == 3
        assert result[0] == [0.0]
        assert result[1] == [1.0]
        assert result[2] == [2.0]
