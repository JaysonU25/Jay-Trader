from datetime import datetime, timezone

import httpx
import pytest

from marketpulse.config import Settings
from marketpulse.db.models import IngestRun
from marketpulse.ingest.jobs import JOB_NAMES, build_client, job_source

# See tests/test_models.py for the full explanation of this opt-in: this
# module uses the `db_session` fixture (bound to the session-scoped event
# loop), so its async tests must run on that same loop.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        alphavantage_api_key="av", fred_api_key="fred",
        finnhub_api_key="fh", ingest_hmac_secret="secret",
    )


def test_job_names_cover_every_scheduled_job():
    assert JOB_NAMES == ("prices", "macro", "crypto", "news", "earnings", "ratings", "fx")


def test_each_job_maps_to_its_source():
    assert job_source("prices") == "alphavantage"
    assert job_source("macro") == "fred"
    assert job_source("crypto") == "coingecko"
    assert job_source("news") == "finnhub"
    assert job_source("earnings") == "finnhub"
    assert job_source("ratings") == "finnhub"
    assert job_source("fx") == "frankfurter"


def test_unknown_job_name_raises():
    with pytest.raises(KeyError):
        job_source("nonsense")


async def test_build_client_seeds_the_daily_counter_from_the_database(
    db_session, settings
):
    db_session.add(IngestRun(source="alphavantage", job="prices", status="success",
                             started_at=datetime.now(timezone.utc), api_calls_used=20))
    await db_session.flush()

    async with httpx.AsyncClient() as http:
        client = await build_client("alphavantage", http, db_session, settings)

    # 5 of the 25-request budget remain.
    for _ in range(5):
        await client._limiter.acquire()

    from marketpulse.core.ratelimit import DailyCapExceeded
    with pytest.raises(DailyCapExceeded):
        await client._limiter.acquire()


async def test_build_client_returns_the_right_class_per_source(db_session, settings):
    from marketpulse.clients.alphavantage import AlphaVantageClient
    from marketpulse.clients.frankfurter import FrankfurterClient

    async with httpx.AsyncClient() as http:
        assert isinstance(
            await build_client("alphavantage", http, db_session, settings),
            AlphaVantageClient,
        )
        assert isinstance(
            await build_client("frankfurter", http, db_session, settings),
            FrankfurterClient,
        )


def test_execute_continues_past_a_failing_job_and_exits_nonzero(monkeypatch):
    """--source all must not abort the whole run when one job fails.

    Regression test for the CLI review finding: a failing job used to kill the
    process before any later job in JOB_NAMES order ever ran.
    """
    from typer.testing import CliRunner

    from marketpulse.config import get_settings
    from marketpulse.ingest import __main__ as cli_main

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av")
    monkeypatch.setenv("FRED_API_KEY", "fred")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")
    get_settings.cache_clear()

    ran: list[str] = []

    async def fake_run_source(job, *, full, session_factory, settings):
        ran.append(job)
        if job == "macro":
            raise RuntimeError("fred is down")
        return 1

    monkeypatch.setattr(cli_main, "run_source", fake_run_source)

    try:
        result = CliRunner().invoke(cli_main.app, ["backfill", "--source", "all"])
    finally:
        get_settings.cache_clear()

    # Every job still ran, including everything after the one that failed.
    assert ran == list(JOB_NAMES)
    assert result.exit_code == 1
    assert "FAILED" in result.stdout
    assert "summary" in result.stdout
    assert "macro" in result.stdout


@pytest.fixture
def session_factory(db_session):
    class _Factory:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return db_session

                async def __aexit__(self_inner, *exc):
                    return False

            return _Ctx()

    return _Factory()


async def test_a_failed_run_reports_the_calls_the_real_client_spent(
    monkeypatch, session_factory, db_session, settings
):
    """End-to-end wiring for the quota-destruction bug: run_source builds the
    client inside the job closure, so without an explicit reporter the failure
    path commits api_calls_used=0 and the next process reseeds its bucket at
    0/25, letting identical retries drain the whole non-renewable budget.
    """
    from sqlalchemy import select

    from marketpulse.ingest import jobs as jobs_module
    from marketpulse.ingest.runner import calls_used_today

    class SpendingClient:
        def __init__(self) -> None:
            self.calls_made = 0

        async def fetch_timeseries(self, start):
            self.calls_made += 4  # four real requests went out
            raise RuntimeError("upstream reset the connection mid-page")

    async def fake_build_client(source, http, session, settings):
        return SpendingClient()

    monkeypatch.setattr(jobs_module, "build_client", fake_build_client)

    with pytest.raises(RuntimeError, match="connection"):
        await jobs_module.run_source("fx", full=True, session_factory=session_factory,
                                     settings=settings)

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "frankfurter"))).scalar_one()
    assert run.status == "failed"
    assert run.api_calls_used == 4
    assert await calls_used_today(db_session, "frankfurter") == 4
