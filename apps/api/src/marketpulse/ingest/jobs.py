from datetime import date, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.clients.alphavantage import AlphaVantageClient
from marketpulse.clients.coingecko import CoinGeckoClient
from marketpulse.clients.finnhub import FinnhubClient
from marketpulse.clients.frankfurter import FrankfurterClient
from marketpulse.clients.fred import FredClient
from marketpulse.config import Settings
from marketpulse.core.ratelimit import RATE_LIMITS, TokenBucket
from marketpulse.ingest.crypto import ingest_crypto_history, ingest_crypto_snapshot
from marketpulse.ingest.fx import ingest_fx
from marketpulse.ingest.macro import ingest_macro
from marketpulse.ingest.news import ingest_earnings, ingest_news, ingest_ratings
from marketpulse.ingest.prices import ingest_prices
from marketpulse.ingest.runner import calls_used_today, run_job
from marketpulse.universe import CRYPTO_LIMIT, EQUITIES, FRED_SERIES, FX_START

JOB_NAMES: tuple[str, ...] = (
    "prices", "macro", "crypto", "news", "earnings", "ratings", "fx",
)

_JOB_SOURCE: dict[str, str] = {
    "prices": "alphavantage",
    "macro": "fred",
    "crypto": "coingecko",
    "news": "finnhub",
    "earnings": "finnhub",
    "ratings": "finnhub",
    "fx": "frankfurter",
}


def job_source(job: str) -> str:
    return _JOB_SOURCE[job]


async def build_client(
    source: str, http: httpx.AsyncClient, session: AsyncSession, settings: Settings
):
    limiter = TokenBucket(RATE_LIMITS[source])
    if RATE_LIMITS[source].daily_cap is not None:
        limiter.set_daily_used(await calls_used_today(session, source))

    if source == "alphavantage":
        return AlphaVantageClient(http, settings.alphavantage_api_key, limiter)
    if source == "fred":
        return FredClient(http, settings.fred_api_key, limiter)
    if source == "finnhub":
        return FinnhubClient(http, settings.finnhub_api_key, limiter)
    if source == "coingecko":
        return CoinGeckoClient(http, limiter, settings.coingecko_api_key)
    if source == "frankfurter":
        return FrankfurterClient(http, limiter)
    raise KeyError(f"unknown source {source}")


async def run_source(job: str, *, full: bool, session_factory, settings: Settings) -> int:
    source = job_source(job)
    today = date.today()

    # The client is built inside `_run`, so `run_job` cannot reach it directly.
    # This cell lets the failure path still record the requests actually spent;
    # it reads 0 in the window before the client exists.
    built: list = []

    def calls_used() -> int:
        return built[0].calls_made if built else 0

    async def _run(session: AsyncSession):
        async with httpx.AsyncClient() as http:
            client = await build_client(source, http, session, settings)
            built.append(client)

            if job == "prices":
                return await ingest_prices(session, client, EQUITIES, full=full)
            if job == "macro":
                return await ingest_macro(session, client, FRED_SERIES)
            if job == "crypto":
                if full:
                    coins = [(c.coin_id, c.name) for c in
                             await client.fetch_top_markets(limit=CRYPTO_LIMIT)]
                    return await ingest_crypto_history(session, client, coins)
                return await ingest_crypto_snapshot(session, client, CRYPTO_LIMIT)
            if job == "news":
                window = 365 if full else 7
                return await ingest_news(session, client, EQUITIES,
                                         today - timedelta(days=window), today)
            if job == "earnings":
                # 180-day window, restricted to this project's universe: the
                # vendor endpoint answers with the entire US market calendar.
                return await ingest_earnings(session, client, EQUITIES,
                                             today - timedelta(days=90),
                                             today + timedelta(days=90))
            if job == "ratings":
                return await ingest_ratings(session, client, EQUITIES)
            if job == "fx":
                return await ingest_fx(session, client, FX_START)
            raise KeyError(f"unknown job {job}")

    return await run_job(session_factory, source, job, _run, calls_used=calls_used)
