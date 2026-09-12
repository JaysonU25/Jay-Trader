from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from marketpulse.clients.fred import FredObservation, FredSeriesMeta
from marketpulse.db.models import Observation, Series
from marketpulse.ingest.macro import ingest_macro

# This module uses the `db_session` fixture, whose connections are bound to the
# session-scoped event loop (see tests/test_models.py for the full rationale).
pytestmark = pytest.mark.asyncio(loop_scope="session")


class FakeFred:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls_made = 0

    async def fetch_series_meta(self, series_id: str) -> FredSeriesMeta:
        self.calls_made += 1
        if series_id in self.fail_on:
            raise RuntimeError(f"{series_id}: upstream 500")
        return FredSeriesMeta(series_id, f"Title for {series_id}", "Percent", "D")

    async def fetch_observations(self, series_id, start=None) -> list[FredObservation]:
        self.calls_made += 1
        return [
            FredObservation(date(2024, 1, 1), Decimal("5.33")),
            FredObservation(date(2024, 1, 2), None),
        ]


async def test_ingest_macro_writes_series_and_observations(db_session):
    result = await ingest_macro(db_session, FakeFred(), ["DFF", "UNRATE"])

    assert (await db_session.execute(
        select(func.count()).select_from(Series))).scalar_one() == 2
    assert (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one() == 4
    assert result.rows_upserted == 4
    assert result.errors == []


async def test_ingest_macro_uses_the_category_map(db_session):
    await ingest_macro(db_session, FakeFred(), ["DFF", "UNRATE"])

    rows = dict((await db_session.execute(
        select(Series.external_id, Series.category))).all())
    assert rows["DFF"] == "rates"
    assert rows["UNRATE"] == "labor"


async def test_one_failing_series_does_not_abort_the_others(db_session):
    result = await ingest_macro(db_session, FakeFred(fail_on={"DFF"}), ["DFF", "UNRATE"])

    assert (await db_session.execute(
        select(func.count()).select_from(Series))).scalar_one() == 1
    assert len(result.errors) == 1
    assert "DFF" in result.errors[0]
    assert result.rows_upserted == 2


async def test_ingest_macro_is_idempotent(db_session):
    await ingest_macro(db_session, FakeFred(), ["DFF"])
    await ingest_macro(db_session, FakeFred(), ["DFF"])

    assert (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one() == 2


async def test_null_observations_are_stored_not_skipped(db_session):
    await ingest_macro(db_session, FakeFred(), ["DFF"])

    values = (await db_session.execute(
        select(Observation.value).order_by(Observation.obs_date))).scalars().all()
    assert values == [Decimal("5.33"), None]
