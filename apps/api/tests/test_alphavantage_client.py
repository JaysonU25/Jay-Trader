import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from marketpulse.clients.alphavantage import AlphaVantageClient
from marketpulse.clients.base import RateLimitedError
from marketpulse.core.ratelimit import Bucket, DailyCapExceeded, TokenBucket


def make_client(http: httpx.AsyncClient, limiter: TokenBucket | None = None):
    async def no_sleep(_: float) -> None:
        return None

    return AlphaVantageClient(
        http=http,
        api_key="test-key",
        limiter=limiter or TokenBucket(Bucket(rate=1000), sleep=no_sleep),
    )


@respx.mock
async def test_fetch_daily_returns_bars_in_ascending_date_order(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_daily.json").read_text())
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        bars = await make_client(http).fetch_daily("AAPL")

    assert [b.trade_date for b in bars] == [date(2024, 4, 30), date(2024, 5, 1)]
    assert bars[1].close == Decimal("169.3000")
    assert bars[1].volume == 50383147


@respx.mock
async def test_full_flag_switches_outputsize(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_daily.json").read_text())
    route = respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.fetch_daily("AAPL", full=False)
        await client.fetch_daily("AAPL", full=True)

    assert route.calls[0].request.url.params["outputsize"] == "compact"
    assert route.calls[1].request.url.params["outputsize"] == "full"
    assert route.calls[0].request.url.params["function"] == "TIME_SERIES_DAILY"
    assert route.calls[0].request.url.params["apikey"] == "test-key"


@respx.mock
async def test_rate_limit_note_in_a_200_body_raises(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_ratelimit.json").read_text())
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError):
            await make_client(http).fetch_daily("AAPL")


@respx.mock
async def test_daily_cap_stops_requests_before_they_are_sent(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_daily.json").read_text())
    route = respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async def no_sleep(_: float) -> None:
        return None

    limiter = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=25), sleep=no_sleep)
    limiter.set_daily_used(25)

    async with httpx.AsyncClient() as http:
        with pytest.raises(DailyCapExceeded):
            await make_client(http, limiter).fetch_daily("AAPL")

    assert route.call_count == 0
