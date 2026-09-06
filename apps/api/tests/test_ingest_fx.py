import pytest
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.clients.frankfurter import FxRate
from marketpulse.db.models import Observation, Series
from marketpulse.ingest.fx import ingest_fx

pytestmark = pytest.mark.asyncio(loop_scope="session")

RATES = [
    FxRate("EUR", "USD", date(2024, 1, 2), Decimal("1.0956")),
    FxRate("EUR", "USD", date(2024, 1, 3), Decimal("1.0919")),
    FxRate("EUR", "GBP", date(2024, 1, 2), Decimal("0.86598")),
]


class FakeFrankfurter:
    """Stands in for FrankfurterClient. No network, no httpx."""

    def __init__(self, rates: list[FxRate], calls: int = 1) -> None:
        self._rates = rates
        self.calls_made = calls

    async def fetch_timeseries(self, start: date, base: str = "EUR") -> list[FxRate]:
        return self._rates


async def test_ingest_fx_creates_one_series_per_currency_pair(db_session):
    result = await ingest_fx(db_session, FakeFrankfurter(RATES), date(2024, 1, 1))

    pairs = (await db_session.execute(select(Series.external_id))).scalars().all()
    assert sorted(pairs) == ["EUR/GBP", "EUR/USD"]
    assert result.rows_upserted == 3
    assert result.errors == []


async def test_ingest_fx_writes_observations_against_the_right_series(db_session):
    await ingest_fx(db_session, FakeFrankfurter(RATES), date(2024, 1, 1))

    usd_id = (await db_session.execute(
        select(Series.id).where(Series.external_id == "EUR/USD"))).scalar_one()
    values = (await db_session.execute(
        select(Observation.value).where(Observation.series_id == usd_id)
        .order_by(Observation.obs_date))).scalars().all()

    assert values == [Decimal("1.0956"), Decimal("1.0919")]


async def test_ingest_fx_is_idempotent(db_session):
    await ingest_fx(db_session, FakeFrankfurter(RATES), date(2024, 1, 1))
    await ingest_fx(db_session, FakeFrankfurter(RATES), date(2024, 1, 1))

    series_count = (await db_session.execute(
        select(func.count()).select_from(Series))).scalar_one()
    obs_count = (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one()

    assert series_count == 2
    assert obs_count == 3


async def test_ingest_fx_reports_api_calls_used(db_session):
    result = await ingest_fx(db_session, FakeFrankfurter(RATES, calls=1), date(2024, 1, 1))
    assert result.api_calls_used == 1


async def test_ingest_fx_categorises_every_series_as_fx(db_session):
    await ingest_fx(db_session, FakeFrankfurter(RATES), date(2024, 1, 1))
    categories = (await db_session.execute(select(Series.category))).scalars().all()
    assert set(categories) == {"fx"}
