"""Run CPU-bound local ONNX inference off the event loop.

`embed_texts(provider="local", ...)` and `Reranker.score()` both run
onnxruntime CPU inference. Called directly, that runs wherever the caller
runs — including on an asyncio event loop, where it blocks every other
in-flight request for its full duration. This module centralises the
offload: a shared semaphore bounds how many inference runs execute
concurrently (each ONNX session already fans out across intra-op threads —
see `rerank.py`), and an optional timeout turns a stuck call into a clean
failure instead of an indefinite hang.

Extracted from `server.py` (2026-09-23) so the fix for a hung embed call
didn't grow an already-oversized file further.
"""

from __future__ import annotations

import asyncio
from typing import Callable, TypeVar

__all__ = ["run_bounded", "embed_local"]

T = TypeVar("T")

# Bounds concurrent CPU-bound local ONNX inference (embedding + reranking).
_LOCAL_INFERENCE_SEMAPHORE = asyncio.Semaphore(2)


async def run_bounded(fn: Callable[..., T], *args, timeout: float | None = None, **kwargs) -> T:
    """Run a blocking callable in a thread, bounded by the shared semaphore.

    `timeout` (seconds) wraps the call in `asyncio.wait_for` and raises
    `TimeoutError` on expiry; omit it to wait indefinitely.
    """
    async with _LOCAL_INFERENCE_SEMAPHORE:
        coro = asyncio.to_thread(fn, *args, **kwargs)
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)


async def embed_local(texts: list[str], cfg) -> list[list[float]]:
    """Run local ONNX embedding off the event loop, bounded and time-boxed.

    Used by `search_docs` (query auto-embed, MMR doc re-embed) and
    `get_context` (topic auto-embed) — all three used to call
    `embed_texts(provider="local", ...)` directly on the event loop, which
    blocked every other in-flight MCP request (including a bare
    `initialize` from a different session) for the duration of the call.
    """
    from gnosis_mcp.embed import embed_texts

    return await run_bounded(
        embed_texts,
        texts,
        provider="local",
        model=cfg.embed_model,
        dim=cfg.embed_dim,
        pooling=cfg.embed_pooling,
        timeout=cfg.embed_timeout,
    )
