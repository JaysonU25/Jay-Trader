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
    coins = await client.fetch_top_markets(limit=limit)

    rows = 0
    for coin in coins:
        values = {
            "price": coin.price_usd,
            "market_cap": coin.market_cap_usd,
            "volume": coin.volume_24h_usd,
        }
        for metric in METRICS:
            series_id = await _series_id(session, coin.coin_id, coin.name, metric)
            rows += await upsert_observations(
                session, series_id, [(coin.as_of, values[metric])]
            )

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made)


async def ingest_crypto_history(
    session: AsyncSession, client, coin_ids: Sequence[str]
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for coin_id in coin_ids:
        try:
            points = await client.fetch_history(coin_id)
            by_metric = {
                "price": [(p.obs_date, p.price_usd) for p in points],
                "market_cap": [(p.obs_date, p.market_cap_usd) for p in points],
                "volume": [(p.obs_date, p.volume_24h_usd) for p in points],
            }
            for metric in METRICS:
                series_id = await _series_id(session, coin_id, coin_id, metric)
                rows += await upsert_observations(session, series_id, by_metric[metric])
        except Exception as exc:
            errors.append(f"{coin_id}: {exc}")

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
