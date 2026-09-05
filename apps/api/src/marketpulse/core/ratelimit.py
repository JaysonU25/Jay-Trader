import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable


class DailyCapExceeded(Exception):
    """Raised when a source's daily request budget is spent."""


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
    "alphavantage": Bucket(rate=5, per=60.0, daily_cap=25),
    "fred": Bucket(rate=100, per=60.0),
    "coingecko": Bucket(rate=20, per=60.0),
    "finnhub": Bucket(rate=50, per=60.0),
    "frankfurter": Bucket(rate=60, per=60.0),
}
