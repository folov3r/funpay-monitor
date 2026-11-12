import asyncio

import httpx
import pytest
from app.parsers.http import HttpClient


async def test_retries_transient_server_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0, max_attempts=3, backoff_factor=0)
        response = await http.get("https://example.com/page")

    assert response.text == "ok"
    assert calls == 3


async def test_retries_transport_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0, max_attempts=2, backoff_factor=0)
        response = await http.get("https://example.com/page")

    assert response.text == "ok"
    assert calls == 2


async def test_does_not_retry_client_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0, max_attempts=3, backoff_factor=0)
        with pytest.raises(httpx.HTTPStatusError):
            await http.get("https://example.com/missing")

    assert calls == 1


async def test_retry_after_header_is_used() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0, max_attempts=2, backoff_factor=0)
        response = await http.get("https://example.com/page")

    assert response.status_code == 200
    assert calls == 2


async def test_requests_are_throttled() -> None:
    moments: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        moments.append(asyncio.get_running_loop().time())
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0.05)
        await http.get("https://example.com/one")
        await http.get("https://example.com/two")

    assert moments[1] - moments[0] >= 0.04


async def test_sends_realistic_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0)
        await http.get("https://example.com/page")

    assert seen[0].startswith("Mozilla/5.0")
    assert "Chrome/" in seen[0]
