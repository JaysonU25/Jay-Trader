import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.coingecko import CoinGeckoClient
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> CoinGeckoClient:
    async def no_sleep(_: float) -> None:
        return None

    return CoinGeckoClient(http=http, limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_top_markets_maps_fields(fixture_path):
    payload = json.loads((fixture_path / "coingecko_markets.json").read_text())
    respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        coins = await make_client(http).fetch_top_markets(limit=2)

    assert [c.coin_id for c in coins] == ["bitcoin", "ethereum"]
    assert coins[0].market_cap_usd == Decimal("1231000000000")
    assert coins[0].as_of == date(2024, 5, 1)


@respx.mock
async def test_fetch_top_markets_requests_one_page(fixture_path):
    payload = json.loads((fixture_path / "coingecko_markets.json").read_text())
    route = respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.fetch_top_markets(limit=20)

    params = route.calls[0].request.url.params
    assert params["vs_currency"] == "usd"
    assert params["order"] == "market_cap_desc"
    assert params["per_page"] == "20"
    assert client.calls_made == 1


@respx.mock
async def test_fetch_history_zips_the_three_arrays(fixture_path):
    payload = json.loads((fixture_path / "coingecko_market_chart.json").read_text())
    respx.get(url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        points = await make_client(http).fetch_history("bitcoin")

    assert len(points) == 2
    assert points[0].obs_date == date(2024, 5, 1)
    assert points[1].price_usd == Decimal("62500.12")
    assert points[1].market_cap_usd == Decimal("1231000000000")


@respx.mock
async def test_fetch_history_does_not_send_the_interval_parameter(fixture_path):
    payload = json.loads((fixture_path / "coingecko_market_chart.json").read_text())
    route = respx.get(
        url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    ).mock(return_value=httpx.Response(200, json=payload))

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_history("bitcoin")

    params = route.calls[0].request.url.params
    assert "interval" not in params
    assert params["days"] == "max"
