"""Embedding provider abstraction and NULL backfill for documentation chunks.

Uses only stdlib (urllib.request) — no new dependencies.
Supports: openai, ollama, and custom OpenAI-compatible endpoints.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

__all__ = ["embed_texts", "embed_pending", "get_provider_url"]

log = logging.getLogger("gnosis_mcp")

# Default URLs per provider
_PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1/embeddings",
    "ollama": "http://localhost:11434/api/embed",
}


@dataclass
class EmbedResult:
    """Result of an embed_pending run."""

    embedded: int
    total_null: int
    errors: int


def get_provider_url(provider: str, custom_url: str | None = None) -> str:
    """Get the API URL for a given provider."""
    if custom_url:
        return custom_url
    url = _PROVIDER_URLS.get(provider)
    if url is None:
        raise ValueError(
            f"No default URL for provider {provider!r}. Set GNOSIS_MCP_EMBED_URL."
        )
    return url


def _build_request_openai(
    texts: list[str], model: str, api_key: str | None, url: str
) -> urllib.request.Request:
    """Build an HTTP request for OpenAI-compatible embedding APIs."""
    payload = json.dumps({"input": texts, "model": model}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(url, data=payload, headers=headers, method="POST")


def _build_request_ollama(
    texts: list[str], model: str, url: str
) -> urllib.request.Request:
    """Build an HTTP request for Ollama embedding API."""
    payload = json.dumps({"model": model, "input": texts}).encode()
    headers = {"Content-Type": "application/json"}
    return urllib.request.Request(url, data=payload, headers=headers, method="POST")


def _parse_response_openai(data: dict) -> list[list[float]]:
    """Parse embeddings from OpenAI-compatible response format.

    Expected: {"data": [{"embedding": [0.1, 0.2, ...]}, ...]}
    """
    return [item["embedding"] for item in data["data"]]


def _parse_response_ollama(data: dict) -> list[list[float]]:
    """Parse embeddings from Ollama response format.

    Expected: {"embeddings": [[0.1, 0.2, ...], ...]}
    """
    return data["embeddings"]


def embed_texts(
    texts: list[str],
    provider: str,
    model: str = "text-embedding-3-small",
    api_key: str | None = None,
    url: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts using the specified provider.

    Args:
        texts: List of text strings to embed.
        provider: One of "openai", "ollama", "custom".
        model: Model name for the embedding API.
        api_key: API key (required for openai, optional for others).
        url: Custom endpoint URL (overrides provider default).

    Returns:
        List of embedding vectors, one per input text.
    """
    if not texts:
        return []

    endpoint = get_provider_url(provider, url)

    if provider == "ollama":
        req = _build_request_ollama(texts, model, endpoint)
    else:
        # openai and custom both use OpenAI-compatible format
        req = _build_request_openai(texts, model, api_key, endpoint)

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())

    if provider == "ollama":
        return _parse_response_ollama(data)
    else:
        return _parse_response_openai(data)


async def embed_pending(
    config,
    provider: str = "openai",
    model: str = "text-embedding-3-small",
    api_key: str | None = None,
    url: str | None = None,
    batch_size: int = 50,
    dry_run: bool = False,
) -> EmbedResult:
    """Find chunks with NULL embeddings and backfill them.

    Args:
        config: GnosisMcpConfig instance.
        provider: Embedding provider ("openai", "ollama", "custom").
        model: Model name for the embedding API.
        api_key: API key for the provider.
        url: Custom endpoint URL.
        batch_size: Number of chunks to embed per batch.
        dry_run: If True, count NULL embeddings without embedding them.

    Returns:
        EmbedResult with counts of embedded, total null, and errors.
    """
    from gnosis_mcp.backend import create_backend

    backend = create_backend(config)
    await backend.startup()
    try:
        total_null = await backend.count_pending_embeddings()

        if dry_run:
            return EmbedResult(embedded=0, total_null=total_null, errors=0)

        if total_null == 0:
            return EmbedResult(embedded=0, total_null=0, errors=0)

        embedded = 0
        errors = 0

        while True:
            rows = await backend.get_pending_embeddings(batch_size)
            if not rows:
                break

            ids = [r["id"] for r in rows]
            texts = [r["content"] for r in rows]

            try:
                vectors = embed_texts(texts, provider, model, api_key, url)
            except Exception:
                log.exception("Embedding batch failed (ids %d-%d)", ids[0], ids[-1])
                errors += len(ids)
                break

            for row_id, vector in zip(ids, vectors):
                await backend.set_embedding(row_id, vector)
                embedded += 1

        return EmbedResult(embedded=embedded, total_null=total_null, errors=errors)
    finally:
        await backend.shutdown()
