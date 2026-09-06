from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from marketpulse.clients.finnhub import EarningsEvent, NewsItem, RatingSnapshot
from marketpulse.db.models import AnalystRating, EarningsCalendar, News
from marketpulse.ingest.news import ingest_earnings, ingest_news, ingest_ratings

# This module uses the `db_session` fixture, whose connections are bound to the
# session-scoped event loop (see tests/test_models.py for the full rationale).
pytestmark = pytest.mark.asyncio(loop_scope="session")

NEWS = [
    NewsItem("AAPL", datetime(2024, 5, 1, 16, 0, tzinfo=timezone.utc),
             "Apple beats estimates", "Reuters", "https://news.test/a",
             "Results topped forecasts.", None),
    NewsItem("AAPL", datetime(2024, 4, 30, 16, 0, tzinfo=timezone.utc),
             "Apple announces buyback", "Bloomberg", "https://news.test/b",
             "Board approved a repurchase.", None),
]

EARNINGS = [
    EarningsEvent("AAPL", date(2024, 5, 2), "amc", Decimal("1.50"),
                  Decimal("1.53"), 90005000000, 90753000000),
    EarningsEvent("MSFT", date(2024, 5, 9), "bmo", Decimal("2.02"),
                  None, 61000000000, None),
]

RATINGS = [RatingSnapshot("AAPL", date(2024, 5, 1), 13, 24, 7, 0, 0)]


class FakeFinnhub:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls_made = 0

    async def fetch_news(self, symbol, start, end):
        self.calls_made += 1
        if symbol in self.fail_on:
            raise RuntimeError(f"{symbol}: upstream 500")
        return [item for item in NEWS if item.symbol == symbol]

    async def fetch_earnings(self, start, end):
        self.calls_made += 1
        return EARNINGS

    async def fetch_ratings(self, symbol):
        self.calls_made += 1
        if symbol in self.fail_on:
            raise RuntimeError(f"{symbol}: upstream 500")
        return [item for item in RATINGS if item.symbol == symbol]


async def test_ingest_news_writes_rows(db_session):
    result = await ingest_news(db_session, FakeFinnhub(), ["AAPL"],
                               date(2024, 4, 25), date(2024, 5, 2))

    assert (await db_session.execute(
        select(func.count()).select_from(News))).scalar_one() == 2
    assert result.rows_upserted == 2


async def test_repeated_news_polls_do_not_duplicate_rows(db_session):
    for _ in range(2):
        await ingest_news(db_session, FakeFinnhub(), ["AAPL"],
                          date(2024, 4, 25), date(2024, 5, 2))

    assert (await db_session.execute(
        select(func.count()).select_from(News))).scalar_one() == 2


async def test_duplicate_url_inside_one_window_does_not_crash(db_session):
    """Finnhub returns overlapping windows; the same URL can appear twice."""

    class DuplicatingFinnhub(FakeFinnhub):
        async def fetch_news(self, symbol, start, end):
            self.calls_made += 1
            return [NEWS[0], NEWS[0]]

    result = await ingest_news(db_session, DuplicatingFinnhub(), ["AAPL"],
                               date(2024, 4, 25), date(2024, 5, 2))

    assert result.rows_upserted == 1
    assert (await db_session.execute(
        select(func.count()).select_from(News))).scalar_one() == 1


async def test_news_failure_on_one_symbol_is_recorded(db_session):
    result = await ingest_news(db_session, FakeFinnhub(fail_on={"AAPL"}),
                               ["AAPL", "MSFT"], date(2024, 4, 25), date(2024, 5, 2))

    assert len(result.errors) == 1
    assert "AAPL" in result.errors[0]


async def test_ingest_earnings_writes_rows_and_keeps_nulls(db_session):
    result = await ingest_earnings(db_session, FakeFinnhub(), ["AAPL", "MSFT"],
                                   date(2024, 5, 1), date(2024, 5, 14))

    assert result.rows_upserted == 2
    msft = await db_session.get(EarningsCalendar, ("MSFT", date(2024, 5, 9)))
    assert msft.eps_actual is None
    assert msft.eps_estimate == Decimal("2.02")


async def test_earnings_rerun_updates_actuals_in_place(db_session):
    await ingest_earnings(db_session, FakeFinnhub(), ["AAPL", "MSFT"],
                            date(2024, 5, 1), date(2024, 5, 14))
    await ingest_earnings(db_session, FakeFinnhub(), ["AAPL", "MSFT"],
                            date(2024, 5, 1), date(2024, 5, 14))

    assert (await db_session.execute(
        select(func.count()).select_from(EarningsCalendar))).scalar_one() == 2


async def test_ingest_ratings_writes_rows(db_session):
    result = await ingest_ratings(db_session, FakeFinnhub(), ["AAPL"])

    stored = await db_session.get(AnalystRating, ("AAPL", date(2024, 5, 1)))
    assert stored.strong_buy == 13
    assert result.rows_upserted == 1


async def test_ingest_ratings_is_idempotent(db_session):
    await ingest_ratings(db_session, FakeFinnhub(), ["AAPL"])
    await ingest_ratings(db_session, FakeFinnhub(), ["AAPL"])

    assert (await db_session.execute(
        select(func.count()).select_from(AnalystRating))).scalar_one() == 1


MARKET_WIDE_EARNINGS = [
    EarningsEvent("AAPL", date(2024, 5, 2), "amc", Decimal("1.50"),
                  Decimal("1.53"), 90005000000, 90753000000),
    EarningsEvent("ZZZZ", date(2024, 5, 3), "bmo", None, None, None, None),
    EarningsEvent("A.VERY.LONG.TICKER.XYZ", date(2024, 5, 6), None,
                  None, None, None, None),  # wider than symbol's String(16)
    EarningsEvent("MSFT", date(2024, 5, 9), "bmo", Decimal("2.02"),
                  None, 61000000000, None),
]


class MarketWideFinnhub(FakeFinnhub):
    """/calendar/earnings takes no symbol filter: it answers with everything."""

    async def fetch_earnings(self, start, end):
        self.calls_made += 1
        return MARKET_WIDE_EARNINGS


async def test_earnings_outside_the_universe_are_dropped(db_session):
    """The endpoint returns the whole US reporting calendar -- thousands of
    events, unbounded, some with symbols too wide for the column. Only the
    project's own universe may be written."""
    result = await ingest_earnings(db_session, MarketWideFinnhub(), ["AAPL", "MSFT"],
                                   date(2024, 5, 1), date(2024, 5, 14))

    assert result.rows_upserted == 2
    stored = sorted((await db_session.execute(
        select(EarningsCalendar.symbol))).scalars().all())
    assert stored == ["AAPL", "MSFT"]


async def test_earnings_with_nothing_in_the_universe_writes_nothing(db_session):
    result = await ingest_earnings(db_session, MarketWideFinnhub(), ["TSLA"],
                                   date(2024, 5, 1), date(2024, 5, 14))

    assert result.rows_upserted == 0
    assert result.errors == []
    assert (await db_session.execute(
        select(func.count()).select_from(EarningsCalendar))).scalar_one() == 0


async def test_a_database_failure_on_one_news_symbol_keeps_the_others(db_session):
    """Spec 6: the writes live inside the per-symbol try, behind a SAVEPOINT,
    so one symbol's DB error cannot roll back the symbols already written."""

    class OverlongSymbolFinnhub(FakeFinnhub):
        async def fetch_news(self, symbol, start, end):
            self.calls_made += 1
            if symbol == "BAD":
                return [NewsItem("A_SYMBOL_FAR_TOO_LONG_FOR_THE_COLUMN",
                                 datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc),
                                 "headline", "src", "https://news.test/bad", None, None)]
            return [item for item in NEWS if item.symbol == symbol]

    result = await ingest_news(db_session, OverlongSymbolFinnhub(),
                               ["AAPL", "BAD"], date(2024, 4, 25), date(2024, 5, 2))

    assert len(result.errors) == 1
    assert "BAD" in result.errors[0]
    assert result.rows_upserted == 2  # AAPL still landed
    assert (await db_session.execute(
        select(func.count()).select_from(News))).scalar_one() == 2
