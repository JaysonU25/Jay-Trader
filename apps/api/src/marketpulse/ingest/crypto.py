from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.ingest.common import upsert_observations, upsert_series
from marketpulse.ingest.runner import JobResult

METRICS = ("price", "market_cap", "volume")
_UNITS = {"price": "USD", "market_cap": "USD", "volume": "USD"}


async def _series_id(session: AsyncSession, coin_id: str, name: str, metric: str) -> int:
    return await upsert_series(
        session,
        source="coingecko",
        external_id=f"{coin_id}:{metric}",
        name=f"{name} {metric.replace('_', ' ')}",
        unit=_UNITS[metric],
        frequency="D",
        category="crypto",
    )


async def ingest_crypto_snapshot(session: AsyncSession, client, limit: int) -> JobResult:
    try:
        coins = await client.fetch_top_markets(limit=limit)
    except Exception as exc:
        return JobResult(api_calls_used=client.calls_made, errors=[f"top_markets: {exc}"])

    rows = 0
    errors: list[str] = []
    for coin in coins:
        # One coin failing must not roll back the coins already written.
        try:
            values = {
                "price": coin.price_usd,
                "market_cap": coin.market_cap_usd,
                "volume": coin.volume_24h_usd,
            }
            written = 0
            async with session.begin_nested():
                for metric in METRICS:
                    series_id = await _series_id(session, coin.coin_id, coin.name, metric)
                    written += await upsert_observations(
                        session, series_id, [(coin.as_of, values[metric])]
                    )
            rows += written
        except Exception as exc:
            errors.append(f"{coin.coin_id}: {exc}")
            continue

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)


async def ingest_crypto_history(
    session: AsyncSession, client, coins: Sequence[tuple[str, str]]
) -> JobResult:
    """Backfill daily history for `coins`, each a `(coin_id, display_name)` pair.

    The display name is threaded through from the markets snapshot so a series
    is called "Bitcoin price" here exactly as it is in the snapshot job, rather
    than flipping to the raw coin id ("bitcoin price") on a backfill.
    """
    rows = 0
    errors: list[str] = []

    for coin_id, name in coins:
        try:
            points = await client.fetch_history(coin_id)
            by_metric = {
                "price": [(p.obs_date, p.price_usd) for p in points],
                "market_cap": [(p.obs_date, p.market_cap_usd) for p in points],
                "volume": [(p.obs_date, p.volume_24h_usd) for p in points],
            }
            written = 0
            async with session.begin_nested():
                for metric in METRICS:
                    series_id = await _series_id(session, coin_id, name, metric)
                    written += await upsert_observations(session, series_id, by_metric[metric])
            rows += written
        except Exception as exc:
            errors.append(f"{coin_id}: {exc}")
            continue

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
