import asyncio
from typing import Any, Awaitable, Callable

import httpx
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from marketpulse.core.ratelimit import RateLimited, TokenBucket


class ApiError(Exception):
    """Any non-retryable failure from a vendor API."""


class RateLimitedError(ApiError, RateLimited):
    """The vendor rejected the request for rate-limit reasons.

    Also a `core.ratelimit.RateLimited`, so ingest jobs can stop a loop on a
    throttle without importing the client layer.
    """


class TransientError(ApiError):
    """A failure worth retrying: 5xx or a timeout."""


_RETRYABLE = (RateLimitedError, TransientError, httpx.TimeoutException,
              httpx.ConnectError)

_BACKOFF = wait_exponential(multiplier=0.5, max=8)


def parse_retry_after(raw: str | None) -> int | None:
    """Read a `Retry-After` header as whole seconds.

    Returns None when the header is absent or is not an integer count of
    seconds (the HTTP-date form is legal but no vendor here emits it, and
    guessing wrong is worse than falling back to the computed backoff).
    """
    if raw is None:
        return None
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def wait_retry_after_or_backoff(retry_state) -> float:
    """Honour the vendor's Retry-After when it gave one; else exponential.

    Spec 5.5: retrying inside a vendor's stated cooldown near-certainly fails
    and spends another request from the daily budget, so the header wins.
    """
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None and outcome.failed else None
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, int) and not isinstance(retry_after, bool) and retry_after >= 0:
        return float(retry_after)
    return _BACKOFF(retry_state)


class BaseClient:
    source: str = "base"
    base_url: str = ""

    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: TokenBucket,
        *,
        retry_sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._http = http
        self._limiter = limiter
        # Injectable so tests can assert the honoured delay without waiting.
        self._retry_sleep = retry_sleep or asyncio.sleep

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
            wait=wait_retry_after_or_backoff,
            sleep=self._retry_sleep,
            reraise=True,
        )
        async def _attempt() -> Any:
            await self._limiter.acquire()
            response = await self._http.get(
                f"{self.base_url}{path}", params=merged, timeout=30.0
            )
            if response.status_code == 429:
                raise RateLimitedError(
                    f"{self.source}: 429 on {path}",
                    retry_after=parse_retry_after(response.headers.get("Retry-After")),
                )
            if response.status_code >= 500:
                raise TransientError(f"{self.source}: {response.status_code} on {path}")
            if response.status_code >= 400:
                raise ApiError(f"{self.source}: {response.status_code} on {path}")
            return response.json()

        return await _attempt()
