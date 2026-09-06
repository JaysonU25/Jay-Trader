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


@respx.mock
async def test_fetch_history_joins_the_arrays_by_position_not_by_timestamp():
    """The three arrays are parallel but the vendor does not promise identical
    epoch-millisecond stamps across them. An exact-timestamp join misses every
    lookup and writes ~80k market caps and volumes as literal zero -- silently,
    with no error and no `partial` status. The fixture cannot reveal this
    because its timestamps are perfectly aligned, so misalign them here.
    """
    payload = {
        "prices": [[1714521600000, 60000.5], [1714608000000, 62500.12]],
        # Same two days, stamped a few seconds apart from `prices`.
        "market_caps": [[1714521603000, 1180000000000], [1714608007000, 1231000000000]],
        "total_volumes": [[1714521599000, 25000000000], [1714607995000, 28400000000]],
    }
    respx.get(url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        points = await make_client(http).fetch_history("bitcoin")

    assert [p.market_cap_usd for p in points] == [
        Decimal("1180000000000"), Decimal("1231000000000"),
    ]
    assert [p.volume_24h_usd for p in points] == [
        Decimal("25000000000"), Decimal("28400000000"),
    ]
    assert all(p.market_cap_usd != Decimal(0) for p in points)


@respx.mock
async def test_a_genuinely_missing_value_becomes_none_not_zero():
    """Spec 4.1 keeps `observation.value` nullable so gaps stay visible in a
    chart. A market cap of zero renders as a real crash to zero instead.
    """
    payload = {
        "prices": [[1714521600000, 60000.5], [1714608000000, 62500.12]],
        "market_caps": [[1714521603000, None], [1714608007000, 1231000000000]],
        "total_volumes": [[1714521599000, 25000000000]],  # short by one entry
    }
    respx.get(url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        points = await make_client(http).fetch_history("bitcoin")

    assert points[0].market_cap_usd is None       # explicit null in the payload
    assert points[1].volume_24h_usd is None       # array ran out
    assert points[0].volume_24h_usd == Decimal("25000000000")
    assert points[1].market_cap_usd == Decimal("1231000000000")


@respx.mock
async def test_fetch_history_tolerates_a_missing_array_entirely():
    payload = {"prices": [[1714521600000, 60000.5]]}
    respx.get(url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        points = await make_client(http).fetch_history("bitcoin")

    assert len(points) == 1
    assert points[0].market_cap_usd is None
    assert points[0].volume_24h_usd is None


@respx.mock
async def test_a_missing_market_field_becomes_none_not_zero(fixture_path):
    payload = json.loads((fixture_path / "coingecko_markets.json").read_text())
    payload[0]["market_cap"] = None
    respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        coins = await make_client(http).fetch_top_markets(limit=2)

    assert coins[0].market_cap_usd is None
