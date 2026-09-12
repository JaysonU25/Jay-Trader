from datetime import date
from decimal import Decimal
from typing import Callable, Hashable, Iterable, Iterator, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import Observation, Series

# The asyncpg driver refuses a statement carrying more than 32767 bind
# parameters ("the number of query arguments cannot exceed 32767"), which is
# stricter than the Postgres wire protocol's own 65535. A batch insert spends
# one parameter per column per row, so the row ceiling is 32767 / n_columns --
# only 4681 rows for the seven-column price and news tables. Every batch
# insert therefore goes through chunk_rows(), which derives its chunk size
# from the row width and leaves headroom below the hard cap.
_MAX_BIND_PARAMS = 30000


def chunk_rows(
    rows: Sequence[dict], n_columns: int | None = None
) -> Iterator[list[dict]]:
    """Yield slices of `rows` small enough for one bind-parameter budget.

    `n_columns` defaults to the width of the first row, which is what every
    call site wants: the payload dicts are uniform by construction.
    """
    if not rows:
        return
    if n_columns is None:
        n_columns = len(rows[0])
    size = max(1, _MAX_BIND_PARAMS // max(n_columns, 1))
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


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

    for chunk in chunk_rows(rows, 3):
        statement = insert(Observation).values(chunk)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Observation.series_id, Observation.obs_date],
                set_={"value": statement.excluded.value},
            )
        )
    return len(rows)
