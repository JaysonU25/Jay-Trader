import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.frankfurter import FrankfurterClient, FxRate
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> FrankfurterClient:
    async def no_sleep(_: float) -> None:
        return None

    return FrankfurterClient(http=http, limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_timeseries_flattens_nested_rates(fixture_path):
    payload = json.loads((fixture_path / "frankfurter_timeseries.json").read_text())
    respx.get(url__startswith="https://api.frankfurter.dev/v1/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        rates = await make_client(http).fetch_timeseries(date(2024, 1, 1))

    assert len(rates) == 6  # 2 dates x 3 currencies
    assert FxRate(base="EUR", quote="USD", obs_date=date(2024, 1, 2),
                  rate=Decimal("1.0956")) in rates


@respx.mock
async def test_fetch_timeseries_uses_one_request(fixture_path):
    payload = json.loads((fixture_path / "frankfurter_timeseries.json").read_text())
    route = respx.get(url__startswith="https://api.frankfurter.dev/v1/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.fetch_timeseries(date(1999, 1, 4))

    assert route.call_count == 1
    assert client.calls_made == 1


@respx.mock
async def test_rate_is_decimal_not_float(fixture_path):
    payload = json.loads((fixture_path / "frankfurter_timeseries.json").read_text())
    respx.get(url__startswith="https://api.frankfurter.dev/v1/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        rates = await make_client(http).fetch_timeseries(date(2024, 1, 1))

    assert all(isinstance(item.rate, Decimal) for item in rates)
