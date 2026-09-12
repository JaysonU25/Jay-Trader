from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.routes.crypto import top_coins
from marketpulse.api.deps import get_session
from marketpulse.api.schemas import (
    DashboardOut, EarningsOut, IngestRunOut, SparklineOut,
)
from marketpulse.db.models import (
    Asset, EarningsCalendar, IngestRun, Observation, PriceDaily, Series,
)

router = APIRouter(tags=["meta"])

POINTS = 30


def _sparkline(label: str, values: list[float]) -> SparklineOut:
    first, last = (values[0], values[-1]) if values else (None, None)
    change = None
    if first not in (None, 0) and last is not None:
        change = (last - first) / first * 100
    return SparklineOut(label=label, latest=last, change_pct=change, points=values)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(session: AsyncSession = Depends(get_session)):
    """One payload for the Overview page instead of seven requests."""
    markets: list[SparklineOut] = []
    assets = (await session.execute(select(Asset).order_by(Asset.symbol))).scalars().all()
    for asset in assets:
        rows = (await session.execute(
            select(PriceDaily.close)
            .where(PriceDaily.asset_id == asset.id)
            .order_by(PriceDaily.trade_date.desc())
            .limit(POINTS)
        )).scalars().all()
        markets.append(_sparkline(asset.symbol, [float(v) for v in reversed(rows)]))

    macro: list[SparklineOut] = []
    series_rows = (await session.execute(
        select(Series).where(Series.source == "fred").order_by(Series.external_id)
    )).scalars().all()
    for item in series_rows:
        rows = (await session.execute(
            select(Observation.value)
            .where(Observation.series_id == item.id, Observation.value.is_not(None))
            .order_by(Observation.obs_date.desc())
            .limit(POINTS)
        )).scalars().all()
        macro.append(_sparkline(item.external_id, [float(v) for v in reversed(rows)]))

    today = date.today()
    earnings = (await session.execute(
        select(EarningsCalendar)
        .where(
            EarningsCalendar.report_date >= today,
            EarningsCalendar.report_date <= today + timedelta(days=14),
        )
        .order_by(EarningsCalendar.report_date)
    )).scalars().all()

    pipeline = (await session.execute(
        select(IngestRun)
        .distinct(IngestRun.source)
        .order_by(IngestRun.source, IngestRun.started_at.desc())
    )).scalars().all()

    return DashboardOut(
        generated_at=datetime.now(timezone.utc),
        markets=markets,
        macro=macro,
        crypto=await top_coins(limit=10, session=session),
        upcoming_earnings=[EarningsOut.model_validate(e) for e in earnings],
        pipeline=[IngestRunOut.model_validate(r) for r in pipeline],
    )
