import httpx
import pytest
import respx

from marketpulse.clients.base import ApiError, BaseClient, RateLimitedError
from marketpulse.core.ratelimit import Bucket, TokenBucket


class DummyClient(BaseClient):
    source = "dummy"
    base_url = "https://example.test"


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
