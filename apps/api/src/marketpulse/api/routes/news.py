from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.deps import get_session
from marketpulse.api.errors import NOT_FOUND_RESPONSE, not_found
from marketpulse.api.schemas import EarningsOut, NewsOut, RatingOut
from marketpulse.db.models import AnalystRating, Asset, EarningsCalendar, News

router = APIRouter(tags=["events"])


@router.get("/news", response_model=list[NewsOut])
async def list_news(
    symbol: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    statement = select(News)
    if symbol is not None:
        statement = statement.where(News.symbol == symbol.upper())
    rows = await session.execute(
        statement.order_by(News.published_at.desc()).limit(limit)
    )
    return rows.scalars().all()


@router.get("/earnings/upcoming", response_model=list[EarningsOut])
async def upcoming_earnings(
    days: int = Query(14, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()
    rows = await session.execute(
        select(EarningsCalendar)
        .where(
            EarningsCalendar.report_date >= today,
            EarningsCalendar.report_date <= today + timedelta(days=days),
        )
        .order_by(EarningsCalendar.report_date, EarningsCalendar.symbol)
    )
    return rows.scalars().all()


@router.get(
    "/ratings/{symbol}", response_model=list[RatingOut], responses=NOT_FOUND_RESPONSE
)
async def ratings(symbol: str, session: AsyncSession = Depends(get_session)):
    asset_id = (
        await session.execute(select(Asset.id).where(Asset.symbol == symbol.upper()))
    ).scalar_one_or_none()
    if asset_id is None:
        raise not_found("symbol", symbol)

    rows = await session.execute(
        select(AnalystRating)
        .where(AnalystRating.symbol == symbol.upper())
        .order_by(AnalystRating.period.desc())
    )
    return rows.scalars().all()
