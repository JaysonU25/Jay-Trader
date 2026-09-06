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
