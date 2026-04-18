"""Local ONNX-based embedding engine.

Uses onnxruntime + tokenizers for CPU inference.
Model auto-downloads from HuggingFace via stdlib urllib (no huggingface-hub dep).
Default: MongoDB/mdbr-leaf-ir (23M params, 23MB quantized, Apache 2.0).
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from pathlib import Path

__all__ = ["LocalEmbedder", "get_embedder"]

log = logging.getLogger("gnosis_mcp")

_DEFAULT_MODEL = "MongoDB/mdbr-leaf-ir"
_DEFAULT_DIM = 384

# Required tokenizer + config files (present in every sentence-transformers repo).
_TOKENIZER_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]

# ONNX filename candidates, tried in order. First one that HTTP 200s wins.
# `model_quantized.onnx` is the usual small/fast variant (optimum export default);
# `model.onnx` is the full-precision fallback.
_ONNX_CANDIDATES = [
    "onnx/model_quantized.onnx",
    "onnx/model.onnx",
]

_HF_BASE = "https://huggingface.co"

# SHA-256 checksums for the bundled default model. Empty dict = no checks for other models
# (user is responsible for pinning). Populate by running `gnosis-mcp embed --compute-checksums`
# after first successful download on a trusted network.
_MODEL_CHECKSUMS: dict[tuple[str, str], str] = {
    # Uncomment and pin once captured from a trusted download:
    # (_DEFAULT_MODEL, "onnx/model_quantized.onnx"): "...",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Module-level singleton — loaded once, reused across calls
_embedder: LocalEmbedder | None = None
_embedder_model: str | None = None


def _get_cache_dir() -> Path:
    """Resolve model cache directory using XDG conventions."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "gnosis-mcp" / "models"


def _download_if_exists(url: str, dest: Path) -> bool:
    """Try to download url to dest. Returns True on success, False on 404.
    Raises on any other network error. Cleans up partial writes."""
    if not url.startswith("https://huggingface.co/"):
        raise RuntimeError(f"Refusing non-HuggingFace HTTPS URL: {url}")
    try:
        urllib.request.urlretrieve(url, str(dest))
        return True
    except urllib.error.HTTPError as exc:
        dest.unlink(missing_ok=True)
        if exc.code == 404:
            return False
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc


def _download_model(model_id: str, cache_dir: Path) -> tuple[Path, str]:
    """Download model files from HuggingFace using stdlib urllib.

    Returns (model_dir, onnx_rel_path) — which ONNX filename we landed on
    (model_quantized.onnx or model.onnx).
    """
    # Sanitize model_id for filesystem: "MongoDB/mdbr-leaf-ir" -> "MongoDB--mdbr-leaf-ir"
    safe_name = model_id.replace("/", "--")
    model_dir = cache_dir / safe_name
    model_dir.mkdir(parents=True, exist_ok=True)

    # Tokenizer files — required.
    for rel_path in _TOKENIZER_FILES:
        local_path = model_dir / rel_path
        if local_path.exists():
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_HF_BASE}/{model_id}/resolve/main/{rel_path}"
        log.info("Downloading %s ...", url)
        if not _download_if_exists(url, local_path):
            raise RuntimeError(f"Missing required file: {url}")
        expected = _MODEL_CHECKSUMS.get((model_id, rel_path))
        if expected:
            actual = _sha256_file(local_path)
            if actual != expected:
                local_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Checksum mismatch for {rel_path}: expected {expected}, got {actual}"
                )

    # ONNX — try candidates in order. First one that exists wins.
    onnx_rel: str | None = None
    for candidate in _ONNX_CANDIDATES:
        cache_path = model_dir / candidate
        if cache_path.exists():
            onnx_rel = candidate
            break

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_HF_BASE}/{model_id}/resolve/main/{candidate}"
        log.info("Trying %s ...", url)
        if _download_if_exists(url, cache_path):
            onnx_rel = candidate
            # Try the .onnx_data sidecar (only present for models split >2GB)
            sidecar_rel = candidate + "_data"
            sidecar_url = f"{_HF_BASE}/{model_id}/resolve/main/{sidecar_rel}"
            sidecar_path = model_dir / sidecar_rel
            _download_if_exists(sidecar_url, sidecar_path)  # 404 is fine
            break

    if onnx_rel is None:
        raise RuntimeError(
            f"No ONNX file found for {model_id}. Tried: {', '.join(_ONNX_CANDIDATES)}"
        )

    return model_dir, onnx_rel


class LocalEmbedder:
    """Local CPU embedding using ONNX Runtime + tokenizers."""

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL,
        cache_dir: Path | None = None,
        dim: int = _DEFAULT_DIM,
    ) -> None:
        self._model_id = model_id
        self._cache_dir = cache_dir or _get_cache_dir()
        self._dim = dim
        self._tokenizer = None
        self._session = None
        self._input_names: list[str] = []

    def _ensure_model(self) -> None:
        """Download model if missing, then load tokenizer + ONNX session."""
        if self._session is not None:
            return

        from tokenizers import Tokenizer
        import onnxruntime as ort

        model_dir, onnx_rel = _download_model(self._model_id, self._cache_dir)

        # Load tokenizer
        tokenizer_path = model_dir / "tokenizer.json"
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))

        # Load ONNX model with CPU provider
        onnx_path = model_dir / onnx_rel
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 4
        self._session = ort.InferenceSession(
            str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = [inp.name for inp in self._session.get_inputs()]
        log.info("Local embedder loaded: model=%s dim=%d", self._model_id, self._dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""
        if not texts:
            return []

        import numpy as np

        self._ensure_model()

        # Tokenize
        self._tokenizer.enable_padding()
        self._tokenizer.enable_truncation(max_length=512)
        encoded = self._tokenizer.encode_batch(texts)

        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)

        # Build feed dict based on model's expected inputs
        feed: dict[str, np.ndarray] = {}
        if "input_ids" in self._input_names:
            feed["input_ids"] = ids
        if "attention_mask" in self._input_names:
            feed["attention_mask"] = attention_mask
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.zeros_like(ids)

        # Run inference → token_embeddings [batch, seq_len, hidden_dim]
        outputs = self._session.run(None, feed)
        token_embeddings = outputs[0]

        # Mean pooling with attention mask
        mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
        summed = (token_embeddings * mask_expanded).sum(axis=1)
        counts = mask_expanded.sum(axis=1).clip(min=1e-9)
        pooled = summed / counts

        # L2 normalization
        norms = np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-12)
        normalized = pooled / norms

        # Matryoshka dimension truncation
        truncated = normalized[:, : self._dim]

        # Re-normalize after truncation
        norms2 = np.linalg.norm(truncated, axis=1, keepdims=True).clip(min=1e-12)
        final = truncated / norms2

        return final.tolist()

    @property
    def dimension(self) -> int:
        return self._dim


def get_embedder(model: str | None = None, dim: int | None = None) -> LocalEmbedder:
    """Get or create the module-level singleton embedder."""
    global _embedder, _embedder_model

    model = model or _DEFAULT_MODEL
    dim = dim or _DEFAULT_DIM

    if _embedder is None or _embedder_model != model:
        _embedder = LocalEmbedder(model_id=model, dim=dim)
        _embedder_model = model

    return _embedder
