from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from marketpulse.clients.alphavantage import DailyBar
from marketpulse.core.ratelimit import DailyCapExceeded
from marketpulse.db.models import Asset, PriceDaily
from marketpulse.ingest.prices import ingest_prices, upsert_asset

# This module uses the `db_session` fixture, whose connections are bound to the
# session-scoped event loop (see tests/test_models.py for the full rationale).
pytestmark = pytest.mark.asyncio(loop_scope="session")

BARS = [
    DailyBar(date(2024, 4, 30), Decimal("173.33"), Decimal("174.99"),
             Decimal("170.00"), Decimal("170.33"), 65934787),
    DailyBar(date(2024, 5, 1), Decimal("169.58"), Decimal("172.705"),
             Decimal("169.11"), Decimal("169.30"), 50383147),
]


class FakeAlphaVantage:
    def __init__(self, *, fail_on: set[str] | None = None, cap_after: int | None = None):
        self.fail_on = fail_on or set()
        self.cap_after = cap_after
        self.calls_made = 0
        self.requested: list[tuple[str, bool]] = []

    async def fetch_daily(self, symbol: str, full: bool = False) -> list[DailyBar]:
        if self.cap_after is not None and self.calls_made >= self.cap_after:
            raise DailyCapExceeded("daily cap of 25 requests reached")
        self.calls_made += 1
        self.requested.append((symbol, full))
        if symbol in self.fail_on:
            raise RuntimeError(f"{symbol}: upstream 500")
        return BARS


async def test_upsert_asset_is_idempotent(db_session):
    first = await upsert_asset(db_session, "AAPL")
    second = await upsert_asset(db_session, "AAPL")

    assert first == second
    assert (await db_session.execute(
        select(func.count()).select_from(Asset))).scalar_one() == 1


async def test_ingest_prices_writes_bars(db_session):
    result = await ingest_prices(db_session, FakeAlphaVantage(), ["AAPL", "MSFT"])

    assert (await db_session.execute(
        select(func.count()).select_from(PriceDaily))).scalar_one() == 4
    assert result.rows_upserted == 4
    assert result.errors == []


async def test_ingest_prices_is_idempotent(db_session):
    await ingest_prices(db_session, FakeAlphaVantage(), ["AAPL"])
    await ingest_prices(db_session, FakeAlphaVantage(), ["AAPL"])

    assert (await db_session.execute(
        select(func.count()).select_from(PriceDaily))).scalar_one() == 2


async def test_full_flag_is_forwarded_to_the_client(db_session):
    client = FakeAlphaVantage()
    await ingest_prices(db_session, client, ["AAPL"], full=True)
    assert client.requested == [("AAPL", True)]


async def test_one_bad_symbol_does_not_stop_the_rest(db_session):
    result = await ingest_prices(
        db_session, FakeAlphaVantage(fail_on={"AAPL"}), ["AAPL", "MSFT"]
    )

    assert len(result.errors) == 1
    assert "AAPL" in result.errors[0]
    assert result.rows_upserted == 2


async def test_daily_cap_stops_the_loop_and_is_recorded(db_session):
    result = await ingest_prices(
        db_session, FakeAlphaVantage(cap_after=1), ["AAPL", "MSFT", "NVDA"]
    )

    assert result.rows_upserted == 2  # only AAPL landed
    assert len(result.errors) == 1
    assert "daily cap" in result.errors[0]


async def test_close_price_survives_the_round_trip(db_session):
    await ingest_prices(db_session, FakeAlphaVantage(), ["AAPL"])

    closes = (await db_session.execute(
        select(PriceDaily.close).order_by(PriceDaily.trade_date))).scalars().all()
    assert closes == [Decimal("170.33"), Decimal("169.30")]
