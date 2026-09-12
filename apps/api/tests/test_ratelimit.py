import pytest

from marketpulse.core.ratelimit import Bucket, DailyCapExceeded, RATE_LIMITS, TokenBucket


class FakeClock:
    """Deterministic monotonic clock; sleeping advances it instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_acquire_is_free_while_tokens_remain():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=5, per=60.0), clock=clock.time, sleep=clock.sleep)

    for _ in range(5):
        await bucket.acquire()

    assert clock.slept == []
    assert bucket.calls_made == 5


async def test_acquire_sleeps_once_the_bucket_is_empty():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=2, per=60.0), clock=clock.time, sleep=clock.sleep)

    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()

    assert len(clock.slept) == 1
    assert clock.slept[0] == pytest.approx(30.0)  # per / rate


async def test_tokens_refill_over_time():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=2, per=60.0), clock=clock.time, sleep=clock.sleep)

    await bucket.acquire()
    await bucket.acquire()
    clock.now += 60.0
    await bucket.acquire()

    assert clock.slept == []


async def test_daily_cap_raises_once_exhausted():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=3),
                         clock=clock.time, sleep=clock.sleep)

    for _ in range(3):
        await bucket.acquire()

    with pytest.raises(DailyCapExceeded):
        await bucket.acquire()


async def test_set_daily_used_counts_against_the_cap():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=25),
                         clock=clock.time, sleep=clock.sleep)
    bucket.set_daily_used(25)

    with pytest.raises(DailyCapExceeded):
        await bucket.acquire()


async def test_rate_limits_match_the_spec():
    # Alpha Vantage diverges from spec 5.4's Bucket(rate=5, per=60). That shape
    # averages correctly but starts full, so the first five requests go out back
    # to back and the vendor refuses them: "Please consider spreading out your
    # free API requests more sparingly (1 request per second)". Serialising at
    # 1 per 1.5s is both under the documented average and inside the burst
    # guard. The daily cap is unchanged.
    assert RATE_LIMITS["alphavantage"] == Bucket(rate=1, per=1.5, daily_cap=25)
    assert RATE_LIMITS["fred"] == Bucket(rate=100, per=60.0)
    assert RATE_LIMITS["coingecko"] == Bucket(rate=20, per=60.0)
    assert RATE_LIMITS["finnhub"] == Bucket(rate=50, per=60.0)
    assert RATE_LIMITS["frankfurter"] == Bucket(rate=60, per=60.0)


async def test_a_partly_spent_daily_budget_allows_exactly_the_remainder():
    """calls_used_today seeds this from the database on every process start, so
    the arithmetic is what stands between a rerun and a drained 25/day quota.
    """
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=25),
                         clock=clock.time, sleep=clock.sleep)
    bucket.set_daily_used(20)

    for _ in range(5):
        await bucket.acquire()

    with pytest.raises(DailyCapExceeded):
        await bucket.acquire()

    assert bucket.calls_made == 5  # the refused acquire spent nothing
