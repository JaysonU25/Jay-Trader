from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from marketpulse.db.models import Observation, Series

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def add_coin(db_session, coin_id, name, price, cap, vol, day=date(2024, 5, 1)):
    # Reuse an existing series for repeat calls with the same coin_id (e.g. to
    # add a later observation) instead of inserting a duplicate row, which
    # would violate the uq_series_source_ext unique constraint.
    for metric, value in (("price", price), ("market_cap", cap), ("volume", vol)):
        external_id = f"{coin_id}:{metric}"
        series_id = (
            await db_session.execute(
                select(Series.id).where(
                    Series.source == "coingecko", Series.external_id == external_id
                )
            )
        ).scalar_one_or_none()
        if series_id is None:
            s = Series(source="coingecko", external_id=external_id,
                       name=f"{name} {metric}", unit="USD", frequency="D",
                       category="crypto")
            db_session.add(s)
            await db_session.flush()
            series_id = s.id
        db_session.add(Observation(series_id=series_id, obs_date=day, value=Decimal(value)))
    await db_session.flush()


async def test_pivots_three_series_into_one_row_per_coin(client, db_session):
    await add_coin(db_session, "bitcoin", "Bitcoin", "62500", "1231000000000", "28400000000")
    body = (await client.get("/v1/crypto/top")).json()
    assert len(body) == 1
    assert body[0]["coin_id"] == "bitcoin"
    assert body[0]["price_usd"] == 62500.0
    assert body[0]["market_cap_usd"] == 1231000000000.0
    assert body[0]["volume_24h_usd"] == 28400000000.0


async def test_orders_by_market_cap_descending(client, db_session):
    await add_coin(db_session, "bitcoin", "Bitcoin", "62500", "1231000000000", "1")
    await add_coin(db_session, "ethereum", "Ethereum", "3010", "304000000000", "1")
    body = (await client.get("/v1/crypto/top")).json()
    assert [c["coin_id"] for c in body] == ["bitcoin", "ethereum"]


async def test_limit_is_respected(client, db_session):
    await add_coin(db_session, "bitcoin", "Bitcoin", "1", "3", "1")
    await add_coin(db_session, "ethereum", "Ethereum", "1", "2", "1")
    body = (await client.get("/v1/crypto/top?limit=1")).json()
    assert [c["coin_id"] for c in body] == ["bitcoin"]


async def test_uses_the_most_recent_observation_per_coin(client, db_session):
    await add_coin(db_session, "bitcoin", "Bitcoin", "60000", "1", "1", date(2024, 4, 30))
    await add_coin(db_session, "bitcoin", "Bitcoin", "62500", "2", "2", date(2024, 5, 1))
    body = (await client.get("/v1/crypto/top")).json()
    assert body[0]["price_usd"] == 62500.0
    assert body[0]["as_of"] == "2024-05-01"


async def test_no_crypto_data_returns_an_empty_list(client, db_session):
    assert (await client.get("/v1/crypto/top")).json() == []


async def add_price_only_coin(db_session, coin_id, name, price, day=date(2024, 5, 1)):
    """A coin with only a price series (no market_cap, no volume observed)."""
    series = Series(source="coingecko", external_id=f"{coin_id}:price",
                     name=f"{name} price", unit="USD", frequency="D",
                     category="crypto")
    db_session.add(series)
    await db_session.flush()
    db_session.add(Observation(series_id=series.id, obs_date=day, value=Decimal(price)))
    await db_session.flush()


async def test_a_coin_with_only_a_price_series_is_not_dropped(client, db_session):
    await add_price_only_coin(db_session, "dogecoin", "Dogecoin", "0.12")
    body = (await client.get("/v1/crypto/top")).json()
    assert len(body) == 1
    assert body[0]["coin_id"] == "dogecoin"
    assert body[0]["price_usd"] == 0.12
    assert body[0]["market_cap_usd"] is None
    assert body[0]["volume_24h_usd"] is None


async def test_a_null_market_cap_sorts_last(client, db_session):
    """A regression putting nulls first would rank an unknown coin above
    Bitcoin on the dashboard."""
    await add_coin(db_session, "bitcoin", "Bitcoin", "62500", "1231000000000", "1")
    await add_price_only_coin(db_session, "mystery", "Mystery Coin", "1.00")
    body = (await client.get("/v1/crypto/top")).json()
    assert [c["coin_id"] for c in body] == ["bitcoin", "mystery"]
