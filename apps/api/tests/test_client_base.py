import httpx
import pytest
import respx

from marketpulse.clients.base import (
    ApiError, BaseClient, RateLimitedError, TransientError, parse_retry_after,
)
from marketpulse.core.ratelimit import Bucket, RateLimited, TokenBucket


class DummyClient(BaseClient):
    source = "dummy"
    base_url = "https://example.test"


class KeyedClient(BaseClient):
    source = "keyed"
    base_url = "https://example.test"

    def _auth_params(self) -> dict[str, str]:
        return {"apikey": "real-key"}


def make_client(http: httpx.AsyncClient) -> DummyClient:
    async def no_sleep(_: float) -> None:
        return None

    limiter = TokenBucket(Bucket(rate=1000, per=60.0), sleep=no_sleep)
    return DummyClient(http=http, limiter=limiter)


@respx.mock
async def test_get_json_returns_parsed_body():
    respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_json("/thing") == {"ok": True}


@respx.mock
async def test_get_json_counts_one_call_per_request():
    respx.get("https://example.test/thing").mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.get_json("/thing")
        await client.get_json("/thing")
        assert client.calls_made == 2


@respx.mock
async def test_retries_on_500_then_succeeds():
    route = respx.get("https://example.test/thing").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_json("/thing") == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_three_attempts_and_raises_rate_limited():
    route = respx.get("https://example.test/thing").mock(return_value=httpx.Response(429))
    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError):
            await make_client(http).get_json("/thing")
    assert route.call_count == 3


@respx.mock
async def test_does_not_retry_on_404():
    route = respx.get("https://example.test/thing").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        with pytest.raises(ApiError):
            await make_client(http).get_json("/thing")
    assert route.call_count == 1


@respx.mock
async def test_gives_up_after_three_consecutive_500s_and_raises_transient():
    route = respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(500)
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(TransientError):
            await make_client(http).get_json("/thing")
    assert route.call_count == 3


@respx.mock
async def test_retries_on_timeout_exception_then_succeeds():
    route = respx.get("https://example.test/thing").mock(
        side_effect=[
            httpx.TimeoutException("timeout"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_json("/thing") == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_retries_on_connect_error_then_succeeds():
    route = respx.get("https://example.test/thing").mock(
        side_effect=[
            httpx.ConnectError("connection failed"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_json("/thing") == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_auth_params_win_over_caller_params_on_collision():
    route = respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async def no_sleep(_: float) -> None:
        return None

    limiter = TokenBucket(Bucket(rate=1000, per=60.0), sleep=no_sleep)
    async with httpx.AsyncClient() as http:
        client = KeyedClient(http=http, limiter=limiter)
        await client.get_json("/thing", params={"apikey": "caller-override", "symbol": "AAPL"})

    assert route.call_count == 1
    request = route.calls[0].request
    assert request.url.params["apikey"] == "real-key"
    assert request.url.params["symbol"] == "AAPL"


class RecordingSleeper:
    """Stands in for tenacity's sleep so retry delays are asserted, not waited."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(float(seconds))


def make_fast_client(http: httpx.AsyncClient, sleeper: RecordingSleeper) -> DummyClient:
    async def no_sleep(_: float) -> None:
        return None

    limiter = TokenBucket(Bucket(rate=1000, per=60.0), sleep=no_sleep)
    return DummyClient(http=http, limiter=limiter, retry_sleep=sleeper)


@respx.mock
async def test_429_retry_honours_the_retry_after_header():
    """Spec 5.5: retrying inside the vendor's stated cooldown near-certainly
    fails and spends another request from a 25/day budget."""
    respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"})
    )
    sleeper = RecordingSleeper()

    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError) as caught:
            await make_fast_client(http, sleeper).get_json("/thing")

    assert caught.value.retry_after == 7
    assert sleeper.slept == [7.0, 7.0]  # not the 1s/2s exponential backoff


@respx.mock
async def test_429_without_retry_after_falls_back_to_exponential_backoff():
    respx.get("https://example.test/thing").mock(return_value=httpx.Response(429))
    sleeper = RecordingSleeper()

    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError) as caught:
            await make_fast_client(http, sleeper).get_json("/thing")

    assert caught.value.retry_after is None
    assert sleeper.slept == [0.5, 1.0]  # wait_exponential(multiplier=0.5)


@respx.mock
async def test_a_malformed_retry_after_falls_back_to_exponential_backoff():
    respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    )
    sleeper = RecordingSleeper()

    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError) as caught:
            await make_fast_client(http, sleeper).get_json("/thing")

    assert caught.value.retry_after is None
    assert sleeper.slept == [0.5, 1.0]  # wait_exponential(multiplier=0.5)


@respx.mock
async def test_retry_after_is_capped_at_zero_not_negative():
    respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "-5"})
    )
    sleeper = RecordingSleeper()

    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError):
            await make_fast_client(http, sleeper).get_json("/thing")

    assert sleeper.slept == [0.0, 0.0]


@respx.mock
async def test_a_500_still_uses_exponential_backoff():
    """Retry-After only applies to the exception that carries one."""
    respx.get("https://example.test/thing").mock(return_value=httpx.Response(500))
    sleeper = RecordingSleeper()

    async with httpx.AsyncClient() as http:
        with pytest.raises(TransientError):
            await make_fast_client(http, sleeper).get_json("/thing")

    assert sleeper.slept == [0.5, 1.0]  # wait_exponential(multiplier=0.5)


def test_parse_retry_after_reads_seconds_and_tolerates_junk():
    assert parse_retry_after("30") == 30
    assert parse_retry_after(" 30 ") == 30
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("soon") is None


def test_rate_limited_error_is_both_an_api_error_and_a_core_rate_limit_signal():
    """ingest/ may not import from clients/, so it catches the core base class."""
    exc = RateLimitedError("throttled", retry_after=12)

    assert isinstance(exc, ApiError)
    assert isinstance(exc, RateLimited)
    assert exc.retry_after == 12
    assert RateLimitedError("throttled").retry_after is None
