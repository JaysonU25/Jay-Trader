from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AssetOut(_Base):
    symbol: str
    name: str
    exchange: str | None = None
    sector: str | None = None


class PriceBarOut(_Base):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class SeriesOut(_Base):
    source: str
    external_id: str
    name: str
    unit: str | None = None
    frequency: str | None = None
    category: str


class ObservationOut(_Base):
    obs_date: date
    value: float | None = None


class CoinOut(_Base):
    coin_id: str
    name: str
    price_usd: float | None = None
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    as_of: date


class FxConversionOut(_Base):
    from_currency: str
    to_currency: str
    amount: float
    rate: float
    result: float
    rate_date: date


class NewsOut(_Base):
    symbol: str
    published_at: datetime
    headline: str
    source: str | None = None
    url: str
    summary: str | None = None
    image_url: str | None = None


class EarningsOut(_Base):
    symbol: str
    report_date: date
    hour: str | None = None
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: int | None = None
    revenue_actual: int | None = None


class RatingOut(_Base):
    symbol: str
    period: date
    strong_buy: int | None = None
    buy: int | None = None
    hold: int | None = None
    sell: int | None = None
    strong_sell: int | None = None


class IngestRunOut(_Base):
    id: int
    source: str
    job: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    rows_upserted: int
    api_calls_used: int
    error: str | None = None

    @field_validator("error", mode="before")
    @classmethod
    def _sanitize_error(cls, value: str | None) -> str | None:
        """Cap what a public, edge-cached route can leak from a stored error.

        Ingest errors may embed statement text, bound parameters, or (via
        httpx's HTTPStatusError) a full request URL with an API key in the
        query string. Keep only the first line, capped at 200 characters, so
        the read boundary is safe regardless of what ingest stores.
        """
        if value is None:
            return None
        first_line = value.splitlines()[0] if value else value
        return first_line[:200]


class SparklineOut(_Base):
    label: str
    latest: float | None = None
    change_pct: float | None = None
    points: list[float]


class DashboardOut(_Base):
    generated_at: datetime
    markets: list[SparklineOut]
    macro: list[SparklineOut]
    crypto: list[CoinOut]
    upcoming_earnings: list[EarningsOut]
    pipeline: list[IngestRunOut]
