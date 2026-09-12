from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Date, DateTime, ForeignKey, Index, Integer, Numeric, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Series(Base):
    __tablename__ = "series"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_series_source_ext"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(4), nullable=True)
    category: Mapped[str] = mapped_column(String(32))


class Observation(Base):
    __tablename__ = "observation"
    __table_args__ = (Index("observation_date_brin", "obs_date", postgresql_using="brin"),)

    series_id: Mapped[int] = mapped_column(ForeignKey("series.id"), primary_key=True)
    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)


class PriceDaily(Base):
    __tablename__ = "price_daily"

    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric)
    high: Mapped[Decimal] = mapped_column(Numeric)
    low: Mapped[Decimal] = mapped_column(Numeric)
    close: Mapped[Decimal] = mapped_column(Numeric)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class News(Base):
    __tablename__ = "news"
    __table_args__ = (Index("news_symbol_time", "symbol", "published_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    headline: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class EarningsCalendar(Base):
    __tablename__ = "earnings_calendar"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    hour: Mapped[str | None] = mapped_column(String(8), nullable=True)
    eps_estimate: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    revenue_estimate: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revenue_actual: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AnalystRating(Base):
    __tablename__ = "analyst_rating"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    strong_buy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sell: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strong_sell: Mapped[int | None] = mapped_column(Integer, nullable=True)


class IngestRun(Base):
    __tablename__ = "ingest_run"
    __table_args__ = (Index("ingest_run_source_time", "source", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    job: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    api_calls_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
