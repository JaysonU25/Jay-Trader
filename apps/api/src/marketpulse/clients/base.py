from typing import Any

import httpx
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from marketpulse.core.ratelimit import TokenBucket


class ApiError(Exception):
    """Any non-retryable failure from a vendor API."""


class RateLimitedError(ApiError):
    """The vendor rejected the request for rate-limit reasons."""


class TransientError(ApiError):
    """A failure worth retrying: 5xx or a timeout."""


_RETRYABLE = (RateLimitedError, TransientError, httpx.TimeoutException,
              httpx.ConnectError)


class BaseClient:
    source: str = "base"
    base_url: str = ""

    def __init__(self, http: httpx.AsyncClient, limiter: TokenBucket) -> None:
        self._http = http
        self._limiter = limiter

    @property
    def calls_made(self) -> int:
        return self._limiter.calls_made

    def _auth_params(self) -> dict[str, str]:
        """Subclasses add their API key here. Base clients need none."""
        return {}

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        merged = {**(params or {}), **self._auth_params()}

        @retry(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=8),
            reraise=True,
        )
        async def _attempt() -> Any:
            await self._limiter.acquire()
            response = await self._http.get(
                f"{self.base_url}{path}", params=merged, timeout=30.0
            )
            if response.status_code == 429:
                raise RateLimitedError(f"{self.source}: 429 on {path}")
            if response.status_code >= 500:
                raise TransientError(f"{self.source}: {response.status_code} on {path}")
            if response.status_code >= 400:
                raise ApiError(f"{self.source}: {response.status_code} on {path}")
            return response.json()

        return await _attempt()
