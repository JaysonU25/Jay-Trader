import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.fred import FredClient, FredObservation
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> FredClient:
    async def no_sleep(_: float) -> None:
        return None

    return FredClient(http=http, api_key="test-key",
                      limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_series_meta_maps_fields(fixture_path):
    payload = json.loads((fixture_path / "fred_series.json").read_text())
    respx.get("https://api.stlouisfed.org/fred/series").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        meta = await make_client(http).fetch_series_meta("CPIAUCSL")

    assert meta.series_id == "CPIAUCSL"
    assert meta.units == "Index 1982-1984=100"
    assert meta.frequency == "M"


@respx.mock
async def test_fetch_observations_maps_dot_to_none(fixture_path):
    payload = json.loads((fixture_path / "fred_observations.json").read_text())
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        observations = await make_client(http).fetch_observations("CPIAUCSL")

    assert len(observations) == 3
    assert observations[0] == FredObservation(date(2024, 1, 1), Decimal("308.417"))
    assert observations[2].value is None


@respx.mock
async def test_api_key_and_file_type_are_sent(fixture_path):
    payload = json.loads((fixture_path / "fred_observations.json").read_text())
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_observations("CPIAUCSL")

    request_url = route.calls[0].request.url
    assert request_url.params["api_key"] == "test-key"
    assert request_url.params["file_type"] == "json"
    assert request_url.params["series_id"] == "CPIAUCSL"


@respx.mock
async def test_start_date_becomes_observation_start(fixture_path):
    payload = json.loads((fixture_path / "fred_observations.json").read_text())
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_observations("CPIAUCSL", start=date(2024, 1, 1))

    assert route.calls[0].request.url.params["observation_start"] == "2024-01-01"
