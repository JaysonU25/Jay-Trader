from datetime import date
from typing import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import AnalystRating, EarningsCalendar, News
from marketpulse.ingest.common import dedupe_by
from marketpulse.ingest.runner import JobResult


async def ingest_news(
    session: AsyncSession, client, symbols: Sequence[str], start: date, end: date
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for symbol in symbols:
        try:
            items = await client.fetch_news(symbol, start, end)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        if not items:
            continue

        # Finnhub can repeat a URL inside a single window; Postgres rejects an
        # ON CONFLICT statement that would touch the same row twice.
        payload = dedupe_by(
            [
                {
                    "symbol": item.symbol, "published_at": item.published_at,
                    "headline": item.headline, "source": item.source, "url": item.url,
                    "summary": item.summary, "image_url": item.image_url,
                }
                for item in items
            ],
            key=lambda row: row["url"],
        )
        statement = insert(News).values(payload)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[News.url],
                set_={
                    "headline": statement.excluded.headline,
                    "summary": statement.excluded.summary,
                    "published_at": statement.excluded.published_at,
                },
            )
        )
        rows += len(payload)

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)


async def ingest_earnings(
    session: AsyncSession, client, start: date, end: date
) -> JobResult:
    try:
        events = await client.fetch_earnings(start, end)
    except Exception as exc:
        return JobResult(api_calls_used=client.calls_made, errors=[f"earnings: {exc}"])

    if not events:
        return JobResult(api_calls_used=client.calls_made)

    payload = dedupe_by(
        [
            {
                "symbol": event.symbol, "report_date": event.report_date,
                "hour": event.hour,
                "eps_estimate": event.eps_estimate, "eps_actual": event.eps_actual,
                "revenue_estimate": event.revenue_estimate,
                "revenue_actual": event.revenue_actual,
            }
            for event in events
        ],
        key=lambda row: (row["symbol"], row["report_date"]),
    )
    statement = insert(EarningsCalendar).values(payload)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[EarningsCalendar.symbol, EarningsCalendar.report_date],
            set_={
                "hour": statement.excluded.hour,
                "eps_estimate": statement.excluded.eps_estimate,
                "eps_actual": statement.excluded.eps_actual,
                "revenue_estimate": statement.excluded.revenue_estimate,
                "revenue_actual": statement.excluded.revenue_actual,
            },
        )
    )
    return JobResult(rows_upserted=len(payload), api_calls_used=client.calls_made)


async def ingest_ratings(
    session: AsyncSession, client, symbols: Sequence[str]
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for symbol in symbols:
        try:
            snapshots = await client.fetch_ratings(symbol)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        if not snapshots:
            continue

        payload = dedupe_by(
            [
                {
                    "symbol": item.symbol, "period": item.period,
                    "strong_buy": item.strong_buy, "buy": item.buy, "hold": item.hold,
                    "sell": item.sell, "strong_sell": item.strong_sell,
                }
                for item in snapshots
            ],
            key=lambda row: (row["symbol"], row["period"]),
        )
        statement = insert(AnalystRating).values(payload)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[AnalystRating.symbol, AnalystRating.period],
                set_={
                    "strong_buy": statement.excluded.strong_buy,
                    "buy": statement.excluded.buy,
                    "hold": statement.excluded.hold,
                    "sell": statement.excluded.sell,
                    "strong_sell": statement.excluded.strong_sell,
                },
            )
        )
        rows += len(payload)

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
