from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from marketpulse.db.models import Observation, Series
from marketpulse.ingest.common import dedupe_by, upsert_observations, upsert_series

# See tests/test_models.py for the full explanation of this opt-in: this
# module uses the `db_session` fixture (bound to the session-scoped event
# loop), so its async tests must run on that same loop.
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_upsert_series_creates_then_returns_same_id(db_session):
    first = await upsert_series(db_session, source="frankfurter", external_id="EUR/USD",
                                name="Euro to US Dollar", unit="rate",
                                frequency="D", category="fx")
    second = await upsert_series(db_session, source="frankfurter", external_id="EUR/USD",
                                 name="Euro to US Dollar (renamed)", unit="rate",
                                 frequency="D", category="fx")

    assert first == second
    count = (await db_session.execute(select(func.count()).select_from(Series))).scalar_one()
    assert count == 1


async def test_upsert_series_updates_mutable_metadata(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="DFF",
                                    name="Old name", unit="Percent",
                                    frequency="D", category="rates")
    await upsert_series(db_session, source="fred", external_id="DFF",
                        name="Federal Funds Effective Rate", unit="Percent",
                        frequency="D", category="rates")

    stored = await db_session.get(Series, series_id)
    assert stored.name == "Federal Funds Effective Rate"


async def test_upsert_observations_is_idempotent(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="DFF",
                                    name="Fed Funds", unit="Percent",
                                    frequency="D", category="rates")
    points = [(date(2024, 1, 1), Decimal("5.33")), (date(2024, 1, 2), Decimal("5.33"))]

    assert await upsert_observations(db_session, series_id, points) == 2
    assert await upsert_observations(db_session, series_id, points) == 2

    count = (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one()
    assert count == 2


async def test_upsert_observations_overwrites_a_revised_value(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="GDPC1",
                                    name="Real GDP", unit="Billions",
                                    frequency="Q", category="growth")
    await upsert_observations(db_session, series_id, [(date(2024, 1, 1), Decimal("100"))])
    await upsert_observations(db_session, series_id, [(date(2024, 1, 1), Decimal("101"))])

    stored = (await db_session.execute(select(Observation))).scalar_one()
    assert stored.value == Decimal("101")


async def test_upsert_observations_accepts_null_values(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="UNRATE",
                                    name="Unemployment", unit="Percent",
                                    frequency="M", category="labor")
    await upsert_observations(db_session, series_id, [(date(1947, 1, 1), None)])

    assert (await db_session.execute(select(Observation))).scalar_one().value is None


async def test_upsert_observations_with_no_points_writes_nothing(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="M2SL",
                                    name="M2", unit="Billions",
                                    frequency="M", category="growth")
    assert await upsert_observations(db_session, series_id, []) == 0


def test_dedupe_by_keeps_the_last_occurrence():
    rows = [{"k": 1, "v": "first"}, {"k": 2, "v": "other"}, {"k": 1, "v": "last"}]

    assert dedupe_by(rows, lambda row: row["k"]) == [
        {"k": 1, "v": "last"},
        {"k": 2, "v": "other"},
    ]


def test_dedupe_by_preserves_first_seen_order():
    rows = [{"k": 3}, {"k": 1}, {"k": 2}, {"k": 1}]

    assert [row["k"] for row in dedupe_by(rows, lambda row: row["k"])] == [3, 1, 2]


async def test_upsert_observations_survives_a_duplicated_date(db_session):
    """CoinGecko appends a current-time point that repeats the last daily date."""
    series_id = await upsert_series(db_session, source="coingecko",
                                    external_id="bitcoin:price", name="Bitcoin price",
                                    unit="USD", frequency="D", category="crypto")
    points = [
        (date(2024, 5, 1), Decimal("62000")),
        (date(2024, 5, 1), Decimal("62500")),  # same day, later snapshot
    ]

    assert await upsert_observations(db_session, series_id, points) == 1
    assert (await db_session.execute(select(Observation))).scalar_one().value == Decimal("62500")
