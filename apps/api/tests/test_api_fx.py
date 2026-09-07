from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from marketpulse.db.models import Observation, Series

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def add_rate(db_session, quote, day, value):
    series_id = (await db_session.execute(
        select(Series.id).where(Series.external_id == f"EUR/{quote}")
    )).scalar_one_or_none()
    if series_id is None:
        s = Series(source="frankfurter", external_id=f"EUR/{quote}",
                   name=f"EUR to {quote}", unit="rate", frequency="D", category="fx")
        db_session.add(s)
        await db_session.flush()
        series_id = s.id
    db_session.add(Observation(series_id=series_id, obs_date=day, value=Decimal(value)))
    await db_session.flush()


async def seed(db_session):
    await add_rate(db_session, "USD", date(2024, 1, 15), "1.0950")
    await add_rate(db_session, "JPY", date(2024, 1, 15), "158.00")
    await add_rate(db_session, "USD", date(2024, 1, 12), "1.0900")


async def test_converts_through_the_eur_base(client, db_session):
    """USD->JPY = (EUR->JPY) / (EUR->USD) = 158.00 / 1.0950."""
    await seed(db_session)
    body = (await client.get(
        "/v1/fx/convert?from=USD&to=JPY&amount=100&date=2024-01-15")).json()
    assert body["rate"] == pytest.approx(158.00 / 1.0950, rel=1e-9)
    assert body["result"] == pytest.approx(100 * 158.00 / 1.0950, rel=1e-9)
    assert body["rate_date"] == "2024-01-15"


async def test_eur_as_source_needs_no_division(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/fx/convert?from=EUR&to=USD&amount=10")).json()
    assert body["rate"] == pytest.approx(1.0950)
    assert body["result"] == pytest.approx(10.950)


async def test_eur_as_target(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/fx/convert?from=USD&to=EUR&amount=1")).json()
    assert body["rate"] == pytest.approx(1 / 1.0950)


async def test_same_currency_is_identity(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/fx/convert?from=USD&to=USD&amount=42")).json()
    assert body["rate"] == 1.0
    assert body["result"] == 42.0


async def test_a_weekend_date_falls_back_to_the_previous_rate(client, db_session):
    """2024-01-13 is a Saturday; the last rate is Friday the 12th."""
    await seed(db_session)
    body = (await client.get(
        "/v1/fx/convert?from=EUR&to=USD&amount=1&date=2024-01-13")).json()
    assert body["rate"] == pytest.approx(1.0900)
    assert body["rate_date"] == "2024-01-12"


async def test_omitting_the_date_uses_the_latest_rate(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/fx/convert?from=EUR&to=USD&amount=1")).json()
    assert body["rate_date"] == "2024-01-15"


async def test_currencies_are_case_insensitive(client, db_session):
    await seed(db_session)
    assert (await client.get("/v1/fx/convert?from=eur&to=usd&amount=1")).status_code == 200


async def test_unknown_currency_is_404(client, db_session):
    await seed(db_session)
    response = await client.get("/v1/fx/convert?from=EUR&to=XYZ&amount=1")
    assert response.status_code == 404
    assert response.json()["detail"]["resource"] == "currency"


async def test_a_date_before_any_rate_is_404(client, db_session):
    await seed(db_session)
    response = await client.get(
        "/v1/fx/convert?from=EUR&to=USD&amount=1&date=1990-01-01")
    assert response.status_code == 404
    assert response.json()["detail"]["resource"] == "rate"
