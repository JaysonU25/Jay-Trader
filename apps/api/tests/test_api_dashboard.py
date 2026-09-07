from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from marketpulse.db.models import (
    Asset, EarningsCalendar, IngestRun, Observation, PriceDaily, Series,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def seed(db_session):
    asset = Asset(symbol="SPY", name="SPDR S&P 500")
    db_session.add(asset)
    await db_session.flush()
    for day, close in enumerate(["500", "505", "510"], start=1):
        db_session.add(PriceDaily(
            asset_id=asset.id, trade_date=date(2024, 5, day),
            open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
            close=Decimal(close), volume=1,
        ))

    cpi = Series(source="fred", external_id="CPIAUCSL", name="CPI",
                 unit="Index", frequency="M", category="inflation")
    db_session.add(cpi)
    await db_session.flush()
    db_session.add_all([
        Observation(series_id=cpi.id, obs_date=date(2024, 3, 1), value=Decimal("300")),
        Observation(series_id=cpi.id, obs_date=date(2024, 4, 1), value=Decimal("306")),
    ])

    db_session.add(EarningsCalendar(
        symbol="SPY", report_date=date.today() + timedelta(days=2)))
    db_session.add(IngestRun(source="fred", job="macro", status="success",
                             started_at=datetime.now(timezone.utc), rows_upserted=5))
    await db_session.flush()


async def test_dashboard_returns_every_section(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/dashboard")).json()
    assert set(body) == {
        "generated_at", "markets", "macro", "crypto",
        "upcoming_earnings", "pipeline",
    }


async def test_market_sparkline_carries_points_and_change(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/dashboard")).json()
    spy = next(m for m in body["markets"] if m["label"] == "SPY")
    assert spy["points"] == [500.0, 505.0, 510.0]
    assert spy["latest"] == 510.0
    assert spy["change_pct"] == pytest.approx((510 - 500) / 500 * 100)


async def test_macro_sparkline_is_built_from_observations(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/dashboard")).json()
    cpi = next(m for m in body["macro"] if m["label"] == "CPIAUCSL")
    assert cpi["points"] == [300.0, 306.0]
    assert cpi["latest"] == 306.0


async def test_dashboard_includes_pipeline_and_earnings(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/dashboard")).json()
    assert [r["source"] for r in body["pipeline"]] == ["fred"]
    assert [e["symbol"] for e in body["upcoming_earnings"]] == ["SPY"]


async def test_an_empty_database_still_returns_a_valid_payload(client, db_session):
    body = (await client.get("/v1/dashboard")).json()
    assert body["markets"] == []
    assert body["macro"] == []
    assert body["crypto"] == []
