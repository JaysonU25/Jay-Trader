from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.deps import get_session
from marketpulse.api.errors import NOT_FOUND_RESPONSE, not_found
from marketpulse.api.schemas import ObservationOut, SeriesOut
from marketpulse.db.models import Observation, Series

router = APIRouter(tags=["series"])


@router.get("/series", response_model=list[SeriesOut])
async def list_series(
    category: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    statement = select(Series)
    if category is not None:
        statement = statement.where(Series.category == category.lower())
    rows = await session.execute(statement.order_by(Series.source, Series.external_id))
    return rows.scalars().all()


# external_id:path because FX ids contain a slash (EUR/USD).
@router.get(
    "/series/{source}/{external_id:path}/observations",
    response_model=list[ObservationOut],
    responses=NOT_FOUND_RESPONSE,
)
async def get_observations(
    source: str,
    external_id: str,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_session),
):
    # external_id is left as-is: it is case-significant data (EUR/USD,
    # bitcoin:price), unlike source/category which are stored lower-case.
    series_id = (
        await session.execute(
            select(Series.id).where(
                Series.source == source.lower(), Series.external_id == external_id
            )
        )
    ).scalar_one_or_none()
    if series_id is None:
        raise not_found("series", f"{source}/{external_id}")

    statement = select(Observation).where(Observation.series_id == series_id)
    if date_from is not None:
        statement = statement.where(Observation.obs_date >= date_from)
    if date_to is not None:
        statement = statement.where(Observation.obs_date <= date_to)

    rows = await session.execute(statement.order_by(Observation.obs_date))
    return rows.scalars().all()
