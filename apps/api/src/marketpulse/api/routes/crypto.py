from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.api.deps import get_session
from marketpulse.api.schemas import CoinOut
from marketpulse.db.models import Observation, Series

router = APIRouter(tags=["crypto"])


@router.get("/crypto/top", response_model=list[CoinOut])
async def top_coins(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Pivot the three per-coin series back into one row.

    Ingest stores price, market cap and volume as separate series so they share
    the observation table with FRED and FX. DISTINCT ON picks each series' most
    recent observation in one pass.
    """
    latest = (
        select(
            Series.external_id.label("external_id"),
            Series.name.label("series_name"),
            Observation.obs_date.label("obs_date"),
            Observation.value.label("value"),
        )
        .join(Observation, Observation.series_id == Series.id)
        .where(Series.source == "coingecko")
        .distinct(Series.external_id)
        .order_by(Series.external_id, Observation.obs_date.desc())
        .subquery()
    )

    rows = (await session.execute(select(latest))).all()

    coins: dict[str, dict] = {}
    for external_id, series_name, obs_date, value in rows:
        coin_id, _, metric = external_id.partition(":")
        entry = coins.setdefault(
            coin_id,
            {"coin_id": coin_id, "name": coin_id, "as_of": obs_date,
             "price_usd": None, "market_cap_usd": None, "volume_24h_usd": None},
        )
        if metric == "price":
            entry["price_usd"] = value
            # "Bitcoin price" -> "Bitcoin"; the snapshot job writes the real name.
            entry["name"] = series_name.removesuffix(" price") or coin_id
        elif metric == "market_cap":
            entry["market_cap_usd"] = value
        elif metric == "volume":
            entry["volume_24h_usd"] = value
        entry["as_of"] = max(entry["as_of"], obs_date)

    ordered = sorted(
        coins.values(),
        key=lambda c: (c["market_cap_usd"] is None, -(c["market_cap_usd"] or 0)),
    )
    return [CoinOut(**c) for c in ordered[:limit]]
