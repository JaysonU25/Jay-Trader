import json
from datetime import date, timezone
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.finnhub import FinnhubClient
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> FinnhubClient:
    async def no_sleep(_: float) -> None:
        return None

    return FinnhubClient(http=http, api_key="test-key",
                         limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_news_maps_epoch_to_utc_datetime(fixture_path):
    payload = json.loads((fixture_path / "finnhub_news.json").read_text())
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        items = await make_client(http).fetch_news(
            "AAPL", date(2024, 4, 25), date(2024, 5, 2)
        )

    assert len(items) == 2
    assert items[0].symbol == "AAPL"
    assert items[0].published_at.tzinfo is timezone.utc
    assert items[0].url == "https://news.test/apple-beats"
    assert items[1].image_url is None  # empty string normalises to None


@respx.mock
async def test_fetch_news_sends_the_token_and_window(fixture_path):
    payload = json.loads((fixture_path / "finnhub_news.json").read_text())
    route = respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_news("AAPL", date(2024, 4, 25), date(2024, 5, 2))

    params = route.calls[0].request.url.params
    assert params["token"] == "test-key"
    assert params["symbol"] == "AAPL"
    assert params["from"] == "2024-04-25"
    assert params["to"] == "2024-05-02"


@respx.mock
async def test_fetch_earnings_handles_null_actuals(fixture_path):
    payload = json.loads((fixture_path / "finnhub_earnings.json").read_text())
    respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        events = await make_client(http).fetch_earnings(date(2024, 5, 1), date(2024, 5, 14))

    assert len(events) == 2
    assert events[0].eps_actual == Decimal("1.53")
    assert events[1].eps_actual is None
    assert events[1].revenue_estimate == 61000000000


@respx.mock
async def test_fetch_ratings_maps_camel_case_fields(fixture_path):
    payload = json.loads((fixture_path / "finnhub_ratings.json").read_text())
    respx.get("https://finnhub.io/api/v1/stock/recommendation").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        ratings = await make_client(http).fetch_ratings("AAPL")

    assert ratings[0].period == date(2024, 5, 1)
    assert ratings[0].strong_buy == 13
    assert ratings[0].strong_sell == 0
