"""Local ONNX-based cross-encoder reranker.

Re-scores an initial search result set using a sequence-pair cross-encoder.
Opt-in: requires the `[reranking]` extra (onnxruntime + tokenizers, already in
`[embeddings]`) and a model whose HuggingFace repo ships an ONNX export.

Default model: `onnx-community/ms-marco-MiniLM-L6-v2-ONNX` (22M params, Apache
2.0, ~90 MB). Cross-encoder style: concatenates query and passage, outputs one
relevance score.

Why opt-in? Cross-encoders add ~50-300 ms per call. On small corpora (<5 000
chunks) where keyword search already hits ~1.0 Hit@5, reranking adds latency
without measurable quality improvement (see `docs/benchmarks.md`). Turn on when
the corpus grows or when queries are paraphrased / natural-language.
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from pathlib import Path

__all__ = ["Reranker", "get_reranker"]

log = logging.getLogger("gnosis_mcp")

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"

_MODEL_FILES = [
    "onnx/model.onnx",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "config.json",
]

_HF_BASE = "https://huggingface.co"

# Reserved for future checksum pinning of the bundled default model.
_MODEL_CHECKSUMS: dict[tuple[str, str], str] = {}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_reranker: Reranker | None = None
_reranker_model: str | None = None


def _get_cache_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "gnosis-mcp" / "rerankers"


def _download_model(model_id: str, cache_dir: Path) -> Path:
    safe_name = model_id.replace("/", "--")
    model_dir = cache_dir / safe_name
    model_dir.mkdir(parents=True, exist_ok=True)

    for rel_path in _MODEL_FILES:
        local_path = model_dir / rel_path
        if local_path.exists():
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_HF_BASE}/{model_id}/resolve/main/{rel_path}"
        if not url.startswith("https://huggingface.co/"):
            raise RuntimeError(f"Refusing non-HuggingFace HTTPS URL: {url}")
        log.info("Downloading reranker asset %s ...", url)
        try:
            urllib.request.urlretrieve(url, str(local_path))
        except Exception as exc:
            local_path.unlink(missing_ok=True)
            # Some repos only ship a subset of optional files (tokenizer_config etc.)
            if rel_path in ("tokenizer_config.json", "special_tokens_map.json", "config.json"):
                log.debug("Optional reranker asset %s not available, continuing", rel_path)
                continue
            raise RuntimeError(f"Failed to download {url}: {exc}") from exc

        expected = _MODEL_CHECKSUMS.get((model_id, rel_path))
        if expected:
            actual = _sha256_file(local_path)
            if actual != expected:
                local_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Checksum mismatch for {rel_path}: expected {expected}, got {actual}."
                )

    return model_dir


class Reranker:
    """CPU-friendly cross-encoder reranker using ONNX Runtime."""

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL,
        cache_dir: Path | None = None,
        max_length: int = 512,
    ) -> None:
        self._model_id = model_id
        self._cache_dir = cache_dir or _get_cache_dir()
        self._max_length = max_length
        self._tokenizer = None
        self._session = None
        self._input_names: list[str] = []

    def _ensure_model(self) -> None:
        if self._session is not None:
            return

        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = _download_model(self._model_id, self._cache_dir)

        tokenizer_path = model_dir / "tokenizer.json"
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_padding()
        self._tokenizer.enable_truncation(max_length=self._max_length)

        onnx_path = model_dir / "onnx" / "model.onnx"
        if not onnx_path.exists():
            # Some repos put it at the top level.
            onnx_path = model_dir / "model.onnx"
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 4
        self._session = ort.InferenceSession(
            str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = [inp.name for inp in self._session.get_inputs()]
        log.info("Reranker loaded: model=%s max_length=%d", self._model_id, self._max_length)

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return a relevance score per passage (higher = more relevant)."""
        if not passages:
            return []
        import numpy as np

        self._ensure_model()

        pairs = [(query, p) for p in passages]
        encoded = self._tokenizer.encode_batch(pairs)

        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)

        feed: dict[str, np.ndarray] = {}
        if "input_ids" in self._input_names:
            feed["input_ids"] = ids
        if "attention_mask" in self._input_names:
            feed["attention_mask"] = attention_mask
        if "token_type_ids" in self._input_names:
            type_ids = np.array([e.type_ids for e in encoded], dtype=np.int64)
            feed["token_type_ids"] = type_ids

        logits = self._session.run(None, feed)[0]
        # ms-marco-MiniLM emits a single score per pair (shape [B, 1]).
        # Squeeze to flat list; sigmoid to map to (0, 1) for interpretability.
        scores = logits.squeeze(-1) if logits.ndim > 1 else logits
        probs = 1.0 / (1.0 + np.exp(-scores))
        return probs.astype(float).tolist()

    def rerank(
        self,
        query: str,
        results: list[dict],
        *,
        text_key: str = "content",
        top_k: int | None = None,
    ) -> list[dict]:
        """Re-sort `results` by cross-encoder score. Returns a new list.

        Each result dict must contain `text_key` (default `content`). The new
        score is stored under `rerank_score`; original `score` is preserved.
        """
        if not results:
            return results
        passages = [r.get(text_key, "") for r in results]
        scores = self.score(query, passages)
        ranked = sorted(zip(scores, results, strict=True), key=lambda pair: pair[0], reverse=True)
        output: list[dict] = []
        for s, r in ranked:
            new = dict(r)
            new["rerank_score"] = round(float(s), 4)
            output.append(new)
        if top_k:
            output = output[:top_k]
        return output


def get_reranker(model: str | None = None) -> Reranker:
    """Get or create the module-level singleton reranker."""
    global _reranker, _reranker_model
    model = model or _DEFAULT_MODEL
    if _reranker is None or _reranker_model != model:
        _reranker = Reranker(model_id=model)
        _reranker_model = model
    return _reranker
