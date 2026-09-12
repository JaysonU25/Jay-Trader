from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from marketpulse.db.models import IngestRun, Observation, Series

# This module's tests share the session-scoped `db_engine` fixture (see
# tests/conftest.py), whose connections are bound to a session-scoped asyncio
# event loop (asyncio_default_fixture_loop_scope = "session" in pyproject.toml).
# Running the test bodies themselves on the default per-function loop would
# hand those connections to a different loop than the one they were opened on
# and raise "attached to a different loop" / "Event loop is closed" errors.
# Opting this module's tests into the same session-scoped loop keeps them
# consistent with their fixtures.
#
# Contract for later tasks: this opt-in is per test module, not global. Any
# new test module that consumes `db_session` or `db_engine` must add this same
# `pytestmark` line; a module that doesn't touch the database (e.g. pure-unit
# tests for the rate limiter or HTTP clients) must NOT add it and will
# correctly get its own per-function event loop.
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_series_and_observation_round_trip(db_session):
    series = Series(
        source="frankfurter", external_id="EUR/USD", name="Euro to US Dollar",
        unit="rate", frequency="D", category="fx",
    )
    db_session.add(series)
    await db_session.flush()

    db_session.add(Observation(series_id=series.id, obs_date=date(2024, 1, 2),
                               value=Decimal("1.0956")))
    await db_session.flush()

    stored = (await db_session.execute(select(Observation))).scalar_one()
    assert stored.value == Decimal("1.0956")
    assert stored.series_id == series.id


async def test_observation_value_is_nullable(db_session):
    series = Series(source="fred", external_id="CPIAUCSL", name="CPI",
                    unit="Index", frequency="M", category="inflation")
    db_session.add(series)
    await db_session.flush()

    db_session.add(Observation(series_id=series.id, obs_date=date(1947, 1, 1), value=None))
    await db_session.flush()

    assert (await db_session.execute(select(Observation))).scalar_one().value is None


async def test_series_source_external_id_is_unique(db_session):
    for _ in range(2):
        db_session.add(Series(source="fred", external_id="DFF", name="Fed Funds",
                              unit="Percent", frequency="D", category="rates"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_ingest_run_defaults_to_zero_counters(db_session):
    run = IngestRun(source="frankfurter", job="fx", status="running",
                    started_at=datetime.now(timezone.utc))
    db_session.add(run)
    await db_session.flush()

    assert run.rows_upserted == 0
    assert run.api_calls_used == 0
    assert run.finished_at is None
