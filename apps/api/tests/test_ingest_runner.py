from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from marketpulse.db.models import IngestRun, Observation
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


async def test_calls_used_today_uses_utc_day_boundary_not_session_timezone(db_session):
    """Guards against func.date(started_at) == func.current_date(), which
    resolves against the Postgres session's TimeZone GUC rather than UTC.
    Build the rows relative to the actual UTC midnight boundary so the test
    is not flaky depending on what time of day it runs.
    """
    utc_now = datetime.now(timezone.utc)
    day_start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)

    just_after_midnight = day_start + timedelta(minutes=30)
    just_before_midnight = day_start - timedelta(minutes=30)  # yesterday, 23:30 UTC

    db_session.add_all([
        IngestRun(source="alphavantage", job="prices", status="success",
                  started_at=just_after_midnight, api_calls_used=7),
        IngestRun(source="alphavantage", job="prices", status="success",
                  started_at=just_before_midnight, api_calls_used=99),
    ])
    await db_session.flush()

    assert await calls_used_today(db_session, "alphavantage") == 7


async def test_a_real_database_error_still_lands_the_failed_audit_row(
    session_factory, db_session
):
    """The failure handler used to UPDATE on a transaction Postgres had already
    aborted. That raised InFailedSQLTransactionError, which replaced the real
    cause, and the ingest_run INSERT -- sharing the dead transaction -- never
    committed, so the table recorded nothing at all.
    """

    async def job(session):
        # A foreign key violation: server-side, so it poisons the transaction.
        await session.execute(
            insert(Observation).values(
                series_id=987654321, obs_date=date(2024, 5, 1), value=Decimal("1")
            )
        )
        return JobResult()

    with pytest.raises(IntegrityError) as caught:
        await run_job(session_factory, "coingecko", "crypto", job)

    # The ORIGINAL cause surfaces, not InFailedSQLTransactionError.
    assert "InFailedSqlTransaction" not in str(caught.value)
    assert "foreign key" in str(caught.value).lower()

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "coingecko"))).scalar_one()
    assert run.status == "failed"
    assert run.job == "crypto"
    assert run.started_at is not None
    assert run.finished_at is not None
    assert "foreign key" in run.error.lower()


async def test_a_failed_run_records_the_api_calls_it_actually_spent(
    session_factory, db_session
):
    """The failure path used to commit api_calls_used=0 regardless of what the
    job burned, so calls_used_today under-reported and the next process seeded
    its token bucket at 0/25 -- letting identical retries drain the whole
    non-renewable daily quota.
    """
    spent = 0

    async def job(session):
        nonlocal spent
        spent = 3  # three real requests went out before the write blew up
        raise RuntimeError("insert failed after the fetches")

    with pytest.raises(RuntimeError):
        await run_job(session_factory, "alphavantage", "prices", job,
                      calls_used=lambda: spent)

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "alphavantage"))).scalar_one()
    assert run.status == "failed"
    assert run.api_calls_used == 3
    # And the daily cap arithmetic now sees them.
    assert await calls_used_today(db_session, "alphavantage") == 3


async def test_the_calls_reporter_may_run_before_the_client_exists(
    session_factory, db_session
):
    """run_source builds the client inside the job, so a failure while building
    it leaves the reporter with nothing to read. That must not mask the error.
    """
    client: list = []

    def calls_used() -> int:
        return client[0].calls_made if client else 0

    async def job(session):
        raise RuntimeError("bad api key")

    with pytest.raises(RuntimeError, match="bad api key"):
        await run_job(session_factory, "finnhub", "news", job, calls_used=calls_used)

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "finnhub"))).scalar_one()
    assert run.status == "failed"
    assert run.api_calls_used == 0


async def test_a_broken_calls_reporter_does_not_mask_the_original_failure(
    session_factory, db_session
):
    def calls_used() -> int:
        raise AttributeError("reporter is broken")

    async def job(session):
        raise RuntimeError("the real problem")

    with pytest.raises(RuntimeError, match="the real problem"):
        await run_job(session_factory, "frankfurter", "fx", job, calls_used=calls_used)

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "frankfurter"))).scalar_one()
    assert run.status == "failed"
    assert run.api_calls_used == 0


async def test_exactly_one_audit_row_lands_per_failed_run(session_factory, db_session):
    async def job(session):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await run_job(session_factory, "fred", "macro", job, calls_used=lambda: 2)

    rows = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "fred"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].api_calls_used == 2


async def test_a_failing_audit_write_never_replaces_the_original_exception():
    """Last-ditch guard: if even the failure row cannot be written, the operator
    must still see what actually went wrong, with the audit failure attached.
    """

    class BrokenSession:
        def add(self, obj):
            pass

        async def flush(self):
            pass

        async def rollback(self):
            pass

        async def commit(self):
            raise OSError("connection to the database is gone")

    class _Factory:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return BrokenSession()

                async def __aexit__(self_inner, *exc):
                    return False

            return _Ctx()

    async def job(session):
        raise RuntimeError("the real problem")

    with pytest.raises(RuntimeError, match="the real problem") as caught:
        await run_job(_Factory(), "fred", "macro", job)

    notes = getattr(caught.value, "__notes__", [])
    assert any("audit row could not be written" in note for note in notes)
