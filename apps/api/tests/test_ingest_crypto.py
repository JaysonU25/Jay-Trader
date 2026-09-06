from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from marketpulse.clients.coingecko import CoinHistoryPoint, CoinSnapshot
from marketpulse.db.models import Observation, Series
from marketpulse.ingest.crypto import ingest_crypto_history, ingest_crypto_snapshot

# This module uses the `db_session` fixture, whose connections are bound to the
# session-scoped event loop (see tests/test_models.py for the full rationale).
pytestmark = pytest.mark.asyncio(loop_scope="session")

SNAPSHOTS = [
    CoinSnapshot("bitcoin", "btc", "Bitcoin", Decimal("62500.12"),
                 Decimal("1231000000000"), Decimal("28400000000"), date(2024, 5, 1)),
    CoinSnapshot("ethereum", "eth", "Ethereum", Decimal("3010.44"),
                 Decimal("361000000000"), Decimal("14200000000"), date(2024, 5, 1)),
]

HISTORY = [
    CoinHistoryPoint(date(2024, 4, 30), Decimal("60000.5"),
                     Decimal("1180000000000"), Decimal("25000000000")),
    CoinHistoryPoint(date(2024, 5, 1), Decimal("62500.12"),
                     Decimal("1231000000000"), Decimal("28400000000")),
]


class FakeCoinGecko:
    def __init__(self, *, fail_on: set[str] | None = None, fail_top_markets: bool = False) -> None:
        self.fail_on = fail_on or set()
        self.fail_top_markets = fail_top_markets
        self.calls_made = 0

    async def fetch_top_markets(self, limit: int = 20) -> list[CoinSnapshot]:
        self.calls_made += 1
        if self.fail_top_markets:
            raise RuntimeError("upstream 503")
        return SNAPSHOTS[:limit]

    async def fetch_history(self, coin_id: str) -> list[CoinHistoryPoint]:
        self.calls_made += 1
        if coin_id in self.fail_on:
            raise RuntimeError(f"{coin_id}: upstream 500")
        return HISTORY


async def test_snapshot_creates_three_series_per_coin(db_session):
    result = await ingest_crypto_snapshot(db_session, FakeCoinGecko(), limit=2)

    ids = sorted((await db_session.execute(select(Series.external_id))).scalars().all())
    assert ids == [
        "bitcoin:market_cap", "bitcoin:price", "bitcoin:volume",
        "ethereum:market_cap", "ethereum:price", "ethereum:volume",
    ]
    assert result.rows_upserted == 6


async def test_snapshot_uses_a_single_api_call(db_session):
    result = await ingest_crypto_snapshot(db_session, FakeCoinGecko(), limit=2)
    assert result.api_calls_used == 1


async def test_snapshot_failure_on_top_markets_is_recorded_not_raised(db_session):
    result = await ingest_crypto_snapshot(
        db_session, FakeCoinGecko(fail_top_markets=True), limit=2
    )

    assert result.rows_upserted == 0
    assert len(result.errors) == 1
    assert "top_markets" in result.errors[0]


async def test_history_writes_one_observation_per_metric_per_day(db_session):
    result = await ingest_crypto_history(db_session, FakeCoinGecko(), ["bitcoin"])

    assert (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one() == 6  # 3 metrics x 2 days
    assert result.rows_upserted == 6


async def test_history_failure_on_one_coin_is_recorded_not_raised(db_session):
    result = await ingest_crypto_history(
        db_session, FakeCoinGecko(fail_on={"bitcoin"}), ["bitcoin", "ethereum"]
    )

    assert len(result.errors) == 1
    assert "bitcoin" in result.errors[0]
    assert result.rows_upserted == 6  # ethereum still landed


async def test_crypto_ingest_is_idempotent(db_session):
    await ingest_crypto_history(db_session, FakeCoinGecko(), ["bitcoin"])
    await ingest_crypto_history(db_session, FakeCoinGecko(), ["bitcoin"])

    assert (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one() == 6


async def test_every_crypto_series_is_categorised_crypto(db_session):
    await ingest_crypto_snapshot(db_session, FakeCoinGecko(), limit=2)
    categories = (await db_session.execute(select(Series.category))).scalars().all()
    assert set(categories) == {"crypto"}
