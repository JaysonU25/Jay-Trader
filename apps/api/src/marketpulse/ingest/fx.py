from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.ingest.common import upsert_observations, upsert_series
from marketpulse.ingest.runner import JobResult


async def ingest_fx(session: AsyncSession, client, start: date) -> JobResult:
    rates = await client.fetch_timeseries(start)

    by_pair: dict[tuple[str, str], list[tuple[date, Decimal | None]]] = defaultdict(list)
    for item in rates:
        by_pair[(item.base, item.quote)].append((item.obs_date, item.rate))

    rows = 0
    for (base, quote), points in by_pair.items():
        series_id = await upsert_series(
            session,
            source="frankfurter",
            external_id=f"{base}/{quote}",
            name=f"{base} to {quote}",
            unit="rate",
            frequency="D",
            category="fx",
        )
        rows += await upsert_observations(session, series_id, points)

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made)
