from datetime import date
from decimal import Decimal

import pytest

from marketpulse.db.models import Asset, PriceDaily

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def seed(db_session):
    asset = Asset(symbol="AAPL", name="Apple Inc.")
    db_session.add(asset)
    await db_session.flush()
    for day, close in [(1, "170.00"), (2, "171.50"), (3, "169.25")]:
        db_session.add(PriceDaily(
            asset_id=asset.id, trade_date=date(2024, 5, day),
            open=Decimal("169"), high=Decimal("172"), low=Decimal("168"),
            close=Decimal(close), volume=1000 + day,
        ))
    await db_session.flush()
    return asset


async def test_lists_assets(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/assets")).json()
    assert body == [{"symbol": "AAPL", "name": "Apple Inc.",
                     "exchange": None, "sector": None}]


async def test_returns_bars_ascending_by_date(client, db_session):
    await seed(db_session)
    body = (await client.get("/v1/prices/AAPL")).json()
    assert [b["trade_date"] for b in body] == ["2024-05-01", "2024-05-02", "2024-05-03"]
    assert body[1]["close"] == 171.5


async def test_symbol_lookup_is_case_insensitive(client, db_session):
    await seed(db_session)
    assert (await client.get("/v1/prices/aapl")).status_code == 200


async def test_date_range_filters_inclusively(client, db_session):
    await seed(db_session)
    body = (await client.get(
        "/v1/prices/AAPL?from=2024-05-02&to=2024-05-02")).json()
    assert [b["trade_date"] for b in body] == ["2024-05-02"]


async def test_unknown_symbol_is_404_with_the_shared_error_body(client, db_session):
    await seed(db_session)
    response = await client.get("/v1/prices/ZZZZ")
    assert response.status_code == 404
    assert response.json()["detail"]["resource"] == "symbol"


async def test_a_known_symbol_with_no_bars_is_an_empty_list_not_404(client, db_session):
    db_session.add(Asset(symbol="MSFT", name="Microsoft"))
    await db_session.flush()
    response = await client.get("/v1/prices/MSFT")
    assert response.status_code == 200
    assert response.json() == []
