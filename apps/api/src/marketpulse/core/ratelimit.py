import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable


class DailyCapExceeded(Exception):
    """Raised when a source's daily request budget is spent."""


class RateLimited(Exception):
    """A vendor refused the request for rate-limit reasons.

    The concrete client-layer exception (`clients.base.RateLimitedError`)
    derives from this. The shared base lives here so ingest jobs can react to
    a throttle without importing the client layer, which the architecture
    rules forbid.

    `retry_after` carries the vendor's `Retry-After` hint in whole seconds
    when one was supplied, and is None otherwise.
    """

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class Bucket:
    rate: int
    per: float = 60.0
    daily_cap: int | None = None


class TokenBucket:
    def __init__(
        self,
        spec: Bucket,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._spec = spec
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(spec.rate)
        self._updated = clock()
        self._daily_used = 0
        self._calls_made = 0
        self._lock = asyncio.Lock()

    @property
    def calls_made(self) -> int:
        return self._calls_made

    def set_daily_used(self, used: int) -> None:
        self._daily_used = used

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._updated
        self._updated = now
        refill = elapsed * (self._spec.rate / self._spec.per)
        self._tokens = min(float(self._spec.rate), self._tokens + refill)

    async def acquire(self) -> None:
        async with self._lock:
            cap = self._spec.daily_cap
            if cap is not None and self._daily_used >= cap:
                raise DailyCapExceeded(
                    f"daily cap of {cap} requests reached"
                )

            self._refill()
            if self._tokens < 1.0:
                await self._sleep(self._spec.per / self._spec.rate)
                self._refill()

            self._tokens -= 1.0
            self._daily_used += 1
            self._calls_made += 1


RATE_LIMITS: dict[str, Bucket] = {
    # 1 per 1.5s, not 5 per 60s. Both average under the documented 5/min, but a
    # 5-per-60s bucket starts full and fires five requests back to back, which
    # trips the burst guard: "Please consider spreading out your free API
    # requests more sparingly (1 request per second)". Serialising is what the
    # vendor actually asks for, and 15 symbols still finish in about 22s.
    "alphavantage": Bucket(rate=1, per=1.5, daily_cap=25),
    "fred": Bucket(rate=100, per=60.0),
    "coingecko": Bucket(rate=20, per=60.0),
    "finnhub": Bucket(rate=50, per=60.0),
    "frankfurter": Bucket(rate=60, per=60.0),
}
