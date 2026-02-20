"""Tests for local ONNX embedding engine (mocked — no model download needed)."""

import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gnosis_mcp.local_embed import (
    LocalEmbedder,
    _DEFAULT_DIM,
    _DEFAULT_MODEL,
    _MODEL_FILES,
    _download_model,
    _get_cache_dir,
    get_embedder,
)

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

needs_numpy = pytest.mark.skipif(not HAS_NUMPY, reason="numpy not installed")


class TestLocalEmbedderInit:
    def test_default_values(self):
        embedder = LocalEmbedder()
        assert embedder._model_id == _DEFAULT_MODEL
        assert embedder._dim == _DEFAULT_DIM
        assert embedder._session is None
        assert embedder._tokenizer is None

    def test_custom_values(self, tmp_path):
        embedder = LocalEmbedder(
            model_id="test/model", cache_dir=tmp_path, dim=128
        )
        assert embedder._model_id == "test/model"
        assert embedder._cache_dir == tmp_path
        assert embedder._dim == 128

    def test_dimension_property(self):
        embedder = LocalEmbedder(dim=256)
        assert embedder.dimension == 256


class TestLocalEmbedderEmbed:
    def test_empty_texts_returns_empty(self):
        embedder = LocalEmbedder()
        result = embedder.embed([])
        assert result == []

    @needs_numpy
    def test_embed_calls_onnx(self, tmp_path):
        """Verify embed() runs the ONNX pipeline with mocked components."""

        embedder = LocalEmbedder(model_id="test/model", cache_dir=tmp_path, dim=4)

        # Mock the tokenizer
        mock_tokenizer = MagicMock()
        mock_encoding = MagicMock()
        mock_encoding.ids = [1, 2, 3, 0]
        mock_encoding.attention_mask = [1, 1, 1, 0]
        mock_tokenizer.encode_batch.return_value = [mock_encoding]

        # Mock the ONNX session
        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "input_ids"
        mock_input2 = MagicMock()
        mock_input2.name = "attention_mask"
        mock_session.get_inputs.return_value = [mock_input, mock_input2]

        # ONNX output: [batch=1, seq=4, hidden=8]
        token_embeddings = np.random.randn(1, 4, 8).astype(np.float32)
        mock_session.run.return_value = [token_embeddings]

        # Set internal state (skip _ensure_model)
        embedder._tokenizer = mock_tokenizer
        embedder._session = mock_session
        embedder._input_names = ["input_ids", "attention_mask"]

        result = embedder.embed(["test text"])

        assert len(result) == 1
        assert len(result[0]) == 4  # truncated to dim=4
        # Verify L2 normalization (unit vector)
        vec = np.array(result[0])
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5

    @needs_numpy
    def test_embed_multiple_texts(self, tmp_path):
        """Verify batch embedding produces correct number of vectors."""

        embedder = LocalEmbedder(model_id="test/model", cache_dir=tmp_path, dim=4)

        mock_tokenizer = MagicMock()
        enc1 = MagicMock(ids=[1, 2], attention_mask=[1, 1])
        enc2 = MagicMock(ids=[3, 4], attention_mask=[1, 1])
        mock_tokenizer.encode_batch.return_value = [enc1, enc2]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "input_ids"
        mock_input2 = MagicMock()
        mock_input2.name = "attention_mask"
        mock_session.get_inputs.return_value = [mock_input, mock_input2]
        token_embeddings = np.random.randn(2, 2, 8).astype(np.float32)
        mock_session.run.return_value = [token_embeddings]

        embedder._tokenizer = mock_tokenizer
        embedder._session = mock_session
        embedder._input_names = ["input_ids", "attention_mask"]

        result = embedder.embed(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 4 for v in result)


class TestGetEmbedder:
    def test_returns_embedder(self):
        # Reset singleton
        import gnosis_mcp.local_embed as mod

        mod._embedder = None
        mod._embedder_model = None

        embedder = get_embedder("test/model", dim=128)
        assert isinstance(embedder, LocalEmbedder)
        assert embedder.dimension == 128

    def test_singleton_reuse(self):
        import gnosis_mcp.local_embed as mod

        mod._embedder = None
        mod._embedder_model = None

        e1 = get_embedder("test/model")
        e2 = get_embedder("test/model")
        assert e1 is e2

    def test_new_model_creates_new_instance(self):
        import gnosis_mcp.local_embed as mod

        mod._embedder = None
        mod._embedder_model = None

        e1 = get_embedder("model-a")
        e2 = get_embedder("model-b")
        assert e1 is not e2


class TestGetCacheDir:
    def test_with_xdg_data_home(self, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
        result = _get_cache_dir()
        assert result == Path("/custom/data/gnosis-mcp/models")

    def test_default_without_xdg(self, monkeypatch):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        result = _get_cache_dir()
        assert result == Path.home() / ".local" / "share" / "gnosis-mcp" / "models"


class TestDownloadModel:
    def test_downloads_all_files(self, tmp_path, monkeypatch):
        downloaded_urls = []

        def mock_urlretrieve(url, path):
            downloaded_urls.append(url)
            Path(path).write_text("mock")

        monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

        result = _download_model("test/model", tmp_path)
        assert result == tmp_path / "test--model"
        assert len(downloaded_urls) == len(_MODEL_FILES)
        for url in downloaded_urls:
            assert "test/model" in url

    def test_skips_existing_files(self, tmp_path, monkeypatch):
        model_dir = tmp_path / "test--model"
        model_dir.mkdir(parents=True)
        for rel in _MODEL_FILES:
            f = model_dir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("cached")

        downloaded_urls = []

        def mock_urlretrieve(url, path):
            downloaded_urls.append(url)

        monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

        _download_model("test/model", tmp_path)
        assert len(downloaded_urls) == 0  # all cached

    def test_cleans_up_partial_on_error(self, tmp_path, monkeypatch):
        def mock_urlretrieve(url, path):
            Path(path).write_text("partial")
            raise OSError("network error")

        monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

        with pytest.raises(RuntimeError, match="Failed to download"):
            _download_model("test/model", tmp_path)

        first_file = tmp_path / "test--model" / _MODEL_FILES[0]
        assert not first_file.exists()  # partial cleaned up

    def test_sanitizes_model_id(self, tmp_path, monkeypatch):
        """Model ID slashes become double-dashes in directory name."""
        def mock_urlretrieve(url, path):
            Path(path).write_text("mock")

        monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

        result = _download_model("org/sub/model", tmp_path)
        assert result.name == "org--sub--model"
