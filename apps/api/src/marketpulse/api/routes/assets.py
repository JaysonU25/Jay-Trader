from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.deps import get_session
from marketpulse.api.errors import NOT_FOUND_RESPONSE, not_found
from marketpulse.api.schemas import AssetOut, PriceBarOut
from marketpulse.db.models import Asset, PriceDaily

router = APIRouter(tags=["prices"])


@router.get("/assets", response_model=list[AssetOut])
async def list_assets(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(Asset).order_by(Asset.symbol))
    return rows.scalars().all()


@router.get(
    "/prices/{symbol}", response_model=list[PriceBarOut], responses=NOT_FOUND_RESPONSE
)
async def get_prices(
    symbol: str,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_session),
):
    asset_id = (
        await session.execute(select(Asset.id).where(Asset.symbol == symbol.upper()))
    ).scalar_one_or_none()
    if asset_id is None:
        raise not_found("symbol", symbol)

    statement = select(PriceDaily).where(PriceDaily.asset_id == asset_id)
    if date_from is not None:
        statement = statement.where(PriceDaily.trade_date >= date_from)
    if date_to is not None:
        statement = statement.where(PriceDaily.trade_date <= date_to)

    rows = await session.execute(statement.order_by(PriceDaily.trade_date))
    return rows.scalars().all()
