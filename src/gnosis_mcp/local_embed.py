"""Local ONNX-based embedding engine.

Uses onnxruntime + tokenizers for CPU inference.
Model auto-downloads from HuggingFace Hub on first use.
Default: MongoDB/mdbr-leaf-ir (23M params, 23MB quantized, Apache 2.0).
"""

from __future__ import annotations

import logging
from pathlib import Path

__all__ = ["LocalEmbedder", "get_embedder"]

log = logging.getLogger("gnosis_mcp")

_DEFAULT_MODEL = "MongoDB/mdbr-leaf-ir"
_DEFAULT_DIM = 384

# Module-level singleton — loaded once, reused across calls
_embedder: LocalEmbedder | None = None
_embedder_model: str | None = None


def _get_cache_dir() -> Path:
    """Resolve model cache directory using XDG conventions."""
    import os

    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "gnosis-mcp" / "models"


class LocalEmbedder:
    """Local CPU embedding using ONNX Runtime + tokenizers."""

    def __init__(self, model_id: str = _DEFAULT_MODEL, cache_dir: Path | None = None,
                 dim: int = _DEFAULT_DIM) -> None:
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

        from huggingface_hub import snapshot_download
        from tokenizers import Tokenizer
        import onnxruntime as ort

        # Download only the files we need
        model_dir = Path(snapshot_download(
            self._model_id,
            cache_dir=str(self._cache_dir),
            allow_patterns=[
                "onnx/model_quantized.onnx",
                "onnx/model_quantized.onnx_data",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
            ],
        ))

        # Load tokenizer
        tokenizer_path = model_dir / "tokenizer.json"
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))

        # Load ONNX model with CPU provider
        onnx_path = model_dir / "onnx" / "model_quantized.onnx"
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
        truncated = normalized[:, :self._dim]

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
