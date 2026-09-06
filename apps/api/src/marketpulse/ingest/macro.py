from datetime import date
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.ingest.common import upsert_observations, upsert_series
from marketpulse.ingest.runner import JobResult
from marketpulse.universe import FRED_CATEGORY


async def ingest_macro(
    session: AsyncSession,
    client,
    series_ids: Sequence[str],
    start: date | None = None,
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for series_id in series_ids:
        try:
            meta = await client.fetch_series_meta(series_id)
            observations = await client.fetch_observations(series_id, start=start)

            internal_id = await upsert_series(
                session,
                source="fred",
                external_id=meta.series_id,
                name=meta.title,
                unit=meta.units,
                frequency=meta.frequency,
                category=FRED_CATEGORY.get(series_id, "other"),
            )
            rows += await upsert_observations(
                session, internal_id,
                [(item.obs_date, item.value) for item in observations],
            )
        except Exception as exc:
            errors.append(f"{series_id}: {exc}")

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
