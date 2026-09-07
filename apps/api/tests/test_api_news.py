from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from marketpulse.db.models import AnalystRating, Asset, EarningsCalendar, News

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def seed(db_session):
    db_session.add(Asset(symbol="AAPL", name="Apple Inc."))
    now = datetime.now(timezone.utc)
    db_session.add_all([
        News(symbol="AAPL", published_at=now - timedelta(hours=1),
             headline="Newer", url="https://n.test/1"),
        News(symbol="AAPL", published_at=now - timedelta(days=2),
             headline="Older", url="https://n.test/2"),
        News(symbol="MSFT", published_at=now, headline="Msft",
             url="https://n.test/3"),
    ])
    today = date.today()
    db_session.add_all([
        EarningsCalendar(symbol="AAPL", report_date=today + timedelta(days=3),
                         hour="amc", eps_estimate=Decimal("1.50")),
        EarningsCalendar(symbol="MSFT", report_date=today + timedelta(days=40),
                         hour="bmo"),
        EarningsCalendar(symbol="XOM", report_date=today - timedelta(days=5)),
    ])
    db_session.add(AnalystRating(symbol="AAPL", period=date(2024, 5, 1),
                                 strong_buy=13, buy=24, hold=7, sell=0, strong_sell=0))
    await db_session.flush()


async def test_news_is_newest_first(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/news")).json()
    assert [n["headline"] for n in body][:2] == ["Msft", "Newer"]


async def test_news_filters_by_symbol(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/news?symbol=AAPL")).json()
    assert {n["symbol"] for n in body} == {"AAPL"}


async def test_news_symbol_filter_is_case_insensitive(client, db_session):
    await seed(db_session)
    assert len((await client.get("/v1/news?symbol=aapl")).json()) == 2


async def test_news_limit_is_capped(client, db_session):
    await seed(db_session)
    assert (await client.get("/v1/news?limit=500")).status_code == 422


async def test_upcoming_earnings_excludes_the_past(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/earnings/upcoming?days=14")).json()
    assert [e["symbol"] for e in body] == ["AAPL"]


async def test_upcoming_earnings_window_widens(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/earnings/upcoming?days=60")).json()
    assert [e["symbol"] for e in body] == ["AAPL", "MSFT"]


async def test_ratings_for_a_symbol(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/ratings/AAPL")).json()
    assert body[0]["strong_buy"] == 13


async def test_ratings_for_an_unrated_symbol_is_an_empty_list(client, db_session):
    await seed(db_session)
    db_session.add(Asset(symbol="ZZZZ", name="Unrated Co"))
    await db_session.flush()
    response = await client.get("/v1/ratings/ZZZZ")
    assert response.status_code == 200
    assert response.json() == []


async def test_ratings_for_an_untracked_symbol_is_404(client, db_session):
    await seed(db_session)
    response = await client.get("/v1/ratings/NOPE")
    assert response.status_code == 404
    assert response.json()["detail"]["resource"] == "symbol"
