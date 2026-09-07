from datetime import date
from decimal import Decimal

import pytest

from marketpulse.db.models import Observation, Series

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def seed(db_session):
    fx = Series(source="frankfurter", external_id="EUR/USD", name="EUR to USD",
                unit="rate", frequency="D", category="fx")
    cpi = Series(source="fred", external_id="CPIAUCSL", name="CPI",
                 unit="Index", frequency="M", category="inflation")
    db_session.add_all([fx, cpi])
    await db_session.flush()
    db_session.add_all([
        Observation(series_id=fx.id, obs_date=date(2024, 1, 2), value=Decimal("1.0956")),
        Observation(series_id=fx.id, obs_date=date(2024, 1, 3), value=Decimal("1.0919")),
        Observation(series_id=cpi.id, obs_date=date(2024, 1, 1), value=None),
    ])
    await db_session.flush()
    return fx, cpi


async def test_lists_every_series(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/series")).json()
    assert {s["external_id"] for s in body} == {"EUR/USD", "CPIAUCSL"}


async def test_filters_by_category(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/series?category=fx")).json()
    assert [s["external_id"] for s in body] == ["EUR/USD"]


async def test_a_slash_in_the_external_id_still_routes(client, db_session):
    """EUR/USD would otherwise parse as two path segments and 404."""
    await seed(db_session)
    response = await client.get("/v1/series/frankfurter/EUR/USD/observations")
    assert response.status_code == 200
    assert [o["obs_date"] for o in response.json()] == ["2024-01-02", "2024-01-03"]


async def test_observations_come_back_ascending(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/series/frankfurter/EUR/USD/observations")).json()
    assert body[0]["value"] == 1.0956


async def test_null_values_are_preserved(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/series/fred/CPIAUCSL/observations")).json()
    assert body == [{"obs_date": "2024-01-01", "value": None}]


async def test_date_range_filters(client, db_session):
    await seed(db_session)
    body = (await client.get(
        "/v1/series/frankfurter/EUR/USD/observations?from=2024-01-03")).json()
    assert [o["obs_date"] for o in body] == ["2024-01-03"]


async def test_unknown_series_is_404(client, db_session):
    await seed(db_session)
    response = await client.get("/v1/series/fred/NOPE/observations")
    assert response.status_code == 404
    assert response.json()["detail"]["resource"] == "series"


async def test_category_filter_is_case_insensitive(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/series?category=FX")).json()
    assert [s["external_id"] for s in body] == ["EUR/USD"]


async def test_source_lookup_is_case_insensitive(client, db_session):
    await seed(db_session)
    response = await client.get("/v1/series/FRANKFURTER/EUR/USD/observations")
    assert response.status_code == 200
    assert [o["obs_date"] for o in response.json()] == ["2024-01-02", "2024-01-03"]
