"""Local ONNX-based cross-encoder reranker.

Re-scores an initial search result set using a sequence-pair cross-encoder.
Opt-in: requires the `[reranking]` extra (onnxruntime + tokenizers, already in
`[embeddings]`) and a model whose HuggingFace repo ships an ONNX export.

Default model: `cross-encoder/ms-marco-MiniLM-L6-v2` (22M params, Apache 2.0,
~90 MB). Cross-encoder style: concatenates query and passage, outputs one
relevance score. It is the same repo `GnosisMcpConfig.rerank_model` defaults to,
so `GNOSIS_MCP_RERANK_MODEL` can be left unset.

Why opt-in? Cross-encoders add ~50-300 ms per call. On small corpora (<5 000
chunks) where keyword search already hits ~1.0 Hit@5, reranking adds latency
without measurable quality improvement (see `docs/benchmarks.md`). Turn on when
the corpus grows or when queries are paraphrased / natural-language.
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

__all__ = ["Reranker", "check_model_available", "get_reranker", "model_is_cached"]

log = logging.getLogger("gnosis_mcp")

DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
_DEFAULT_MODEL = DEFAULT_MODEL

_MODEL_FILES = [
    "onnx/model.onnx",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "config.json",
]

#: Assets a model must have to be usable. The rest of `_MODEL_FILES` is optional.
_REQUIRED_MODEL_FILES = ("tokenizer.json",)

#: Repos occasionally keep the export at the top level instead of under onnx/.
_ONNX_CANDIDATES = ("onnx/model.onnx", "model.onnx")

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


def _model_dir(model_id: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or _get_cache_dir()) / model_id.replace("/", "--")


def model_is_cached(model_id: str, cache_dir: Path | None = None) -> bool:
    """True when every required asset for `model_id` is already on disk."""
    model_dir = _model_dir(model_id, cache_dir)
    if not all((model_dir / rel_path).exists() for rel_path in _REQUIRED_MODEL_FILES):
        return False
    return any((model_dir / rel_path).exists() for rel_path in _ONNX_CANDIDATES)


def _http_status(exc: BaseException) -> str:
    """`HTTP 401` for urllib's HTTPError, otherwise the exception class name."""
    code = getattr(exc, "code", None)
    return f"HTTP {code}" if isinstance(code, int) else type(exc).__name__


def _unavailable_message(model_id: str, url: str, exc: BaseException) -> str:
    """Actionable one-liner for a reranker asset that cannot be fetched.

    Reranking degrades quietly by design — `search_docs` catches the failure and
    returns unranked results — so a model that 401s (the shape the old default
    `onnx-community/ms-marco-MiniLM-L6-v2-ONNX` had) looked like a slow search
    rather than a misconfiguration. Every message that reaches an operator now
    names the model, the HTTP status, and both ways to fix it.
    """
    return (
        f"Reranker model '{model_id}' is unusable: could not fetch {url} "
        f"({_http_status(exc)}). Set GNOSIS_MCP_RERANK_MODEL to a fetchable "
        f"cross-encoder (e.g. '{DEFAULT_MODEL}'), or turn reranking off with "
        f"GNOSIS_MCP_RERANK_ENABLED=false. Searches keep returning unranked "
        f"results until then."
    )


def check_model_available(
    model_id: str, timeout: float = 3.0, cache_dir: Path | None = None
) -> tuple[bool, str]:
    """Probe whether a reranker repo can be fetched, without downloading it.

    Returns `(ok, detail)`. Used by `serve` to complain at startup instead of
    degrading every search to unranked results. HEAD requests only: the weights
    are ~90 MB and are still fetched lazily on first use. A model already in the
    cache short-circuits without touching the network.
    """
    if model_is_cached(model_id, cache_dir):
        return True, "cached"
    last_reason = "no ONNX export found"
    for rel_path in _ONNX_CANDIDATES:
        url = f"{_HF_BASE}/{model_id}/resolve/main/{rel_path}"
        if not url.startswith("https://huggingface.co/"):
            return False, f"refusing non-HuggingFace URL: {url}"
        try:
            request = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status < 400:  # noqa: PLR2004 — urllib raises >= 400 anyway
                    return True, url
        except urllib.error.HTTPError as exc:
            last_reason = f"{_http_status(exc)} for {rel_path}"
            if exc.code != 404:  # noqa: PLR2004 — any other status won't change per path
                break
        except Exception as exc:
            last_reason = f"{type(exc).__name__} for {rel_path}"
            break
    return False, last_reason


def _download_model(model_id: str, cache_dir: Path) -> Path:
    model_dir = _model_dir(model_id, cache_dir)
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
            raise RuntimeError(_unavailable_message(model_id, url, exc)) from exc

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
            # Six decimals, not four: sigmoid saturates for an irrelevant pair
            # (logit -11 → 1.2e-05), and rounding those to 4 dp collapsed
            # *differently scored* passages to the same 0.0 — so a client
            # comparing the scores it was shown could not reproduce the order it
            # was given. Logits below roughly -14 still collapse; that is the
            # sigmoid's limit, not the rounding's.
            new["rerank_score"] = round(float(s), 6)
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
