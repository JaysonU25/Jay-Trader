from typing import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.core.ratelimit import DailyCapExceeded, RateLimited
from marketpulse.db.models import Asset, PriceDaily
from marketpulse.ingest.common import chunk_rows, dedupe_by
from marketpulse.ingest.runner import JobResult


async def upsert_asset(session: AsyncSession, symbol: str, name: str | None = None) -> int:
    statement = (
        insert(Asset)
        .values(symbol=symbol, name=name or symbol)
        .on_conflict_do_update(index_elements=[Asset.symbol], set_={"symbol": symbol})
        .returning(Asset.id)
    )
    return (await session.execute(statement)).scalar_one()


async def _insert_bars(session: AsyncSession, payload: list[dict]) -> None:
    for chunk in chunk_rows(payload):
        statement = insert(PriceDaily).values(chunk)
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


async def ingest_prices(
    session: AsyncSession, client, symbols: Sequence[str], full: bool = False
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for symbol in symbols:
        # The database writes sit inside the try alongside the fetch: a failure
        # on one symbol must not escape and roll back the symbols already done
        # (spec 6). The SAVEPOINT keeps that promise honest -- a server-side
        # error would otherwise poison the whole transaction, so unwinding just
        # this symbol is what lets the loop carry on and the rest commit.
        try:
            bars = await client.fetch_daily(symbol, full=full)

            written = 0
            async with session.begin_nested():
                asset_id = await upsert_asset(session, symbol)
                payload = dedupe_by(
                    [
                        {
                            "asset_id": asset_id, "trade_date": bar.trade_date,
                            "open": bar.open, "high": bar.high, "low": bar.low,
                            "close": bar.close, "volume": bar.volume,
                        }
                        for bar in bars
                    ],
                    key=lambda row: row["trade_date"],
                )
                if payload:
                    await _insert_bars(session, payload)
                    written = len(payload)
            rows += written
        except DailyCapExceeded as exc:
            # The budget is gone for the day. Stop rather than burn retries.
            errors.append(f"{symbol}: {exc}")
            break
        except RateLimited as exc:
            # The vendor is throttling us. Every further symbol would block in
            # the token bucket and then fail the same way, so stop here too.
            errors.append(f"{symbol}: {exc}")
            break
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
