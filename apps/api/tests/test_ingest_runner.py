from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from marketpulse.db.models import IngestRun
from marketpulse.ingest.runner import JobResult, calls_used_today, run_job

# See tests/test_models.py for the full explanation of this opt-in: this
# module uses the `db_session` fixture (bound to the session-scoped event
# loop), so its async tests must run on that same loop.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def session_factory(db_session):
    """run_job asks for a session per run; hand it the transactional test session."""

    class _Factory:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return db_session

                async def __aexit__(self_inner, *exc):
                    return False

            return _Ctx()

    return _Factory()


async def test_successful_job_records_success(session_factory, db_session):
    async def job(session):
        return JobResult(rows_upserted=42, api_calls_used=1)

    run_id = await run_job(session_factory, "frankfurter", "fx", job)

    run = await db_session.get(IngestRun, run_id)
    assert run.status == "success"
    assert run.rows_upserted == 42
    assert run.api_calls_used == 1
    assert run.finished_at is not None
    assert run.error is None


async def test_job_with_errors_and_rows_records_partial(session_factory, db_session):
    async def job(session):
        return JobResult(rows_upserted=14, api_calls_used=15, errors=["TSLA: 404"])

    run_id = await run_job(session_factory, "alphavantage", "prices", job)

    run = await db_session.get(IngestRun, run_id)
    assert run.status == "partial"
    assert run.rows_upserted == 14
    assert "TSLA: 404" in run.error


async def test_raising_job_records_failed_and_reraises(session_factory, db_session):
    async def job(session):
        raise RuntimeError("bad api key")

    with pytest.raises(RuntimeError):
        await run_job(session_factory, "fred", "macro", job)

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "fred"))).scalar_one()
    assert run.status == "failed"
    assert run.rows_upserted == 0
    assert "bad api key" in run.error


async def test_calls_used_today_sums_only_todays_runs(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all([
        IngestRun(source="alphavantage", job="prices", status="success",
                  started_at=now, api_calls_used=10),
        IngestRun(source="alphavantage", job="prices", status="success",
                  started_at=now - timedelta(days=2), api_calls_used=15),
        IngestRun(source="fred", job="macro", status="success",
                  started_at=now, api_calls_used=15),
    ])
    await db_session.flush()

    assert await calls_used_today(db_session, "alphavantage") == 10
