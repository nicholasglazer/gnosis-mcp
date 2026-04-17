"""Regression test: /health must bypass Bearer auth even when GNOSIS_MCP_API_KEY is set.

Monitoring / load balancer probes hit /health without credentials. A 401 on
/health silently breaks operational alerting. Caught during v0.10.13 e2e.
"""

from __future__ import annotations

import pytest


class _CollectingSend:
    """Capture ASGI messages so we can assert on the status code."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)


async def _inner_app_ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _scope(path: str, auth: str | None = None) -> dict:
    headers = []
    if auth is not None:
        headers.append((b"authorization", auth.encode()))
    return {"type": "http", "method": "GET", "path": path, "headers": headers}


async def _noop_receive() -> dict:
    return {"type": "http.request"}


@pytest.mark.asyncio
async def test_health_bypasses_auth():
    from gnosis_mcp.rest import ApiKeyMiddleware

    mw = ApiKeyMiddleware(_inner_app_ok, api_key="the-real-key")
    send = _CollectingSend()
    await mw(_scope("/health"), _noop_receive, send)
    assert send.messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_api_requires_auth():
    from gnosis_mcp.rest import ApiKeyMiddleware

    mw = ApiKeyMiddleware(_inner_app_ok, api_key="the-real-key")
    send = _CollectingSend()
    await mw(_scope("/api/search"), _noop_receive, send)
    assert send.messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_api_accepts_correct_bearer():
    from gnosis_mcp.rest import ApiKeyMiddleware

    mw = ApiKeyMiddleware(_inner_app_ok, api_key="the-real-key")
    send = _CollectingSend()
    await mw(_scope("/api/search", auth="Bearer the-real-key"), _noop_receive, send)
    assert send.messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_api_rejects_wrong_bearer():
    from gnosis_mcp.rest import ApiKeyMiddleware

    mw = ApiKeyMiddleware(_inner_app_ok, api_key="the-real-key")
    send = _CollectingSend()
    await mw(_scope("/api/search", auth="Bearer wrong"), _noop_receive, send)
    assert send.messages[0]["status"] == 401
