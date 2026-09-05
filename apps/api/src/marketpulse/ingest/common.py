from datetime import date
from decimal import Decimal
from typing import Callable, Hashable, Iterable, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import Observation, Series

# Postgres caps a statement at 65535 bind parameters; observation rows use 3 each.
_CHUNK = 5000


def dedupe_by(
    rows: Sequence[dict], key: Callable[[dict], Hashable]
) -> list[dict]:
    """Collapse rows sharing a conflict key, keeping the last occurrence.

    Postgres refuses an ON CONFLICT DO UPDATE statement that would touch the
    same row twice, so every batch insert filters through this first.
    """
    merged: dict[Hashable, dict] = {}
    for row in rows:
        merged[key(row)] = row
    return list(merged.values())


async def upsert_series(
    session: AsyncSession,
    *,
    source: str,
    external_id: str,
    name: str,
    unit: str | None,
    frequency: str | None,
    category: str,
) -> int:
    statement = (
        insert(Series)
        .values(source=source, external_id=external_id, name=name,
                unit=unit, frequency=frequency, category=category)
        .on_conflict_do_update(
            index_elements=[Series.source, Series.external_id],
            set_={"name": name, "unit": unit, "frequency": frequency, "category": category},
        )
        .returning(Series.id)
    )
    return (await session.execute(statement)).scalar_one()


async def upsert_observations(
    session: AsyncSession,
    series_id: int,
    points: Iterable[tuple[date, Decimal | None]],
) -> int:
    rows = dedupe_by(
        [
            {"series_id": series_id, "obs_date": obs_date, "value": value}
            for obs_date, value in points
        ],
        key=lambda row: row["obs_date"],
    )
    if not rows:
        return 0

    for start in range(0, len(rows), _CHUNK):
        chunk = rows[start:start + _CHUNK]
        statement = insert(Observation).values(chunk)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Observation.series_id, Observation.obs_date],
                set_={"value": statement.excluded.value},
            )
        )
    return len(rows)
