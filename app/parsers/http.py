"""HTTP client with request throttling and retry with exponential backoff."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 30.0


class HttpClient:
    """Small async HTTP client that is polite to the target site.

    Guarantees a minimum delay between consecutive requests and retries
    transient failures (network errors, 429 and 5xx responses).
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        delay: float = 3.0,
        timeout: float = 20.0,
        max_attempts: int = 3,
        backoff_factor: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self._user_agent = user_agent
        self._delay = max(0.0, delay)
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._backoff_factor = max(0.0, backoff_factor)
        self._owns_client = client is None
        self._client = client
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    @property
    def _http_client(self) -> httpx.AsyncClient:
        """Create the underlying client lazily, so parse-only usage has no resources."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        return self._client

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Perform a GET request, retrying transient failures."""
        request_headers = {"User-Agent": self._user_agent}
        if headers:
            request_headers.update(headers)

        for attempt in range(1, self._max_attempts + 1):
            await self._throttle()

            try:
                response = await self._http_client.get(url, params=params, headers=request_headers)
            except httpx.TransportError as exc:
                if attempt >= self._max_attempts:
                    raise
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Request to %s failed (%s), retry %s/%s in %.1fs",
                    url,
                    exc,
                    attempt,
                    self._max_attempts - 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_attempts:
                delay = self._retry_after(response) or self._backoff_delay(attempt)
                logger.warning(
                    "Request to %s returned HTTP %s, retry %s/%s in %.1fs",
                    url,
                    response.status_code,
                    attempt,
                    self._max_attempts - 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            response.raise_for_status()
            return response

        raise RuntimeError("unreachable: retry loop finished without a response")

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _throttle(self) -> None:
        """Wait until the configured delay since the previous request has passed."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_for = self._next_request_at - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                now = loop.time()
            self._next_request_at = now + self._delay

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._backoff_factor * (2 ** (attempt - 1))
        return min(delay, MAX_BACKOFF_SECONDS)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None
