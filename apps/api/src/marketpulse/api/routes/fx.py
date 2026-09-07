import math
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.deps import get_session
from marketpulse.api.errors import NOT_FOUND_RESPONSE, not_found
from marketpulse.api.schemas import FxConversionOut
from marketpulse.db.models import Observation, Series

router = APIRouter(tags=["fx"])

BASE = "EUR"
SOURCE = "frankfurter"


async def _rate_on(
    session: AsyncSession, currency: str, on: date | None
) -> tuple[Decimal, date] | None:
    """Most recent EUR->currency rate on or before `on`.

    Returns None when the currency has no series at all; the caller
    distinguishes that from "no rate that early", which is a different 404.
    """
    if currency == BASE:
        return Decimal(1), on or date.today()

    series_id = (
        await session.execute(
            select(Series.id).where(
                Series.source == SOURCE, Series.external_id == f"{BASE}/{currency}"
            )
        )
    ).scalar_one_or_none()
    if series_id is None:
        return None

    statement = select(Observation.value, Observation.obs_date).where(
        Observation.series_id == series_id,
        Observation.value.is_not(None),
        Observation.value != 0,
    )
    if on is not None:
        statement = statement.where(Observation.obs_date <= on)

    row = (
        await session.execute(statement.order_by(Observation.obs_date.desc()).limit(1))
    ).first()
    return (row[0], row[1]) if row else (None, None)


@router.get(
    "/fx/convert", response_model=FxConversionOut, responses=NOT_FOUND_RESPONSE
)
async def convert(
    from_currency: str = Query(..., alias="from", min_length=3, max_length=3),
    to_currency: str = Query(..., alias="to", min_length=3, max_length=3),
    amount: float = Query(1.0, allow_inf_nan=False),
    on: date | None = Query(None, alias="date"),
    session: AsyncSession = Depends(get_session),
):
    source = from_currency.upper()
    target = to_currency.upper()

    if source == target:
        return FxConversionOut(
            from_currency=source, to_currency=target, amount=amount,
            rate=1.0, result=amount, rate_date=on or date.today(),
        )

    resolved = []
    for currency in (source, target):
        found = await _rate_on(session, currency, on)
        if found is None:
            raise not_found("currency", currency)
        if found[0] is None:
            raise not_found("rate", f"{currency} on or before {on}")
        resolved.append(found)

    (source_rate, source_date), (target_rate, target_date) = resolved
    rate = float(target_rate) / float(source_rate)
    result = amount * rate
    if not math.isfinite(result):
        raise HTTPException(
            status_code=422, detail="conversion result is not finite"
        )

    return FxConversionOut(
        from_currency=source, to_currency=target, amount=amount,
        rate=rate, result=result,
        rate_date=min(source_date, target_date),
    )
