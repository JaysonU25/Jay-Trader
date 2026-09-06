from typing import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.core.ratelimit import DailyCapExceeded
from marketpulse.db.models import Asset, PriceDaily
from marketpulse.ingest.runner import JobResult


async def upsert_asset(session: AsyncSession, symbol: str, name: str | None = None) -> int:
    statement = (
        insert(Asset)
        .values(symbol=symbol, name=name or symbol)
        .on_conflict_do_update(index_elements=[Asset.symbol], set_={"symbol": symbol})
        .returning(Asset.id)
    )
    return (await session.execute(statement)).scalar_one()


async def ingest_prices(
    session: AsyncSession, client, symbols: Sequence[str], full: bool = False
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for symbol in symbols:
        try:
            bars = await client.fetch_daily(symbol, full=full)
        except DailyCapExceeded as exc:
            # The budget is gone for the day. Stop rather than burn retries.
            errors.append(f"{symbol}: {exc}")
            break
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        asset_id = await upsert_asset(session, symbol)
        payload = [
            {
                "asset_id": asset_id, "trade_date": bar.trade_date,
                "open": bar.open, "high": bar.high, "low": bar.low,
                "close": bar.close, "volume": bar.volume,
            }
            for bar in bars
        ]
        if not payload:
            continue

        statement = insert(PriceDaily).values(payload)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[PriceDaily.asset_id, PriceDaily.trade_date],
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "volume": statement.excluded.volume,
                },
            )
        )
        rows += len(payload)

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
