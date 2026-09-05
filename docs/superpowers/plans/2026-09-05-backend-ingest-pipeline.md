# Backend Ingest Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python backend that pulls five financial APIs into Postgres, with every ingest job idempotent, rate-limited, and recorded in an audit table.

**Architecture:** Three strictly separated layers. `clients/` turn HTTP responses into frozen dataclasses and never touch the database. `ingest/` map those dataclasses to rows and upsert them, and never make HTTP calls. `core/` holds the async token-bucket rate limiter and HMAC verification. Every job runs inside a wrapper that opens an `ingest_run` row, so partial failures are recorded rather than swallowed.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async) + asyncpg, Alembic, httpx, tenacity, pydantic-settings, Typer, pytest + pytest-asyncio + respx, Docker Compose for local Postgres, `uv` for dependency management.

## Global Constraints

- Python 3.12 exactly. Not 3.14 (asyncpg/pydantic wheel coverage).
- Package name `marketpulse`, source layout `apps/api/src/marketpulse/`.
- **Clients never import from `db/` or `ingest/`.** Ingest never imports `httpx`.
- Every database write is `INSERT ... ON CONFLICT DO UPDATE`. No exceptions.
- Every multi-row batch insert passes its rows through `dedupe_by` (Task 6) on the same key as its `index_elements` first. Postgres raises `ON CONFLICT DO UPDATE command cannot affect row a second time` when one statement touches a row twice, and two vendors emit such duplicates.
- Local Postgres runs as a native Windows service on port 5433, not Docker. `docker-compose.yml` is still committed as the documented path for other machines, but do not expect a Docker daemon here.
- All secrets read from environment via `config.py`. No key literal in any committed file.
- `pytest.ini` option `asyncio_mode = auto`. No `@pytest.mark.asyncio` decorators.
- No network access in any test. `respx` intercepts all HTTP.
- Rate limits, verbatim: alphavantage 5/60s + 25/day cap; fred 100/60s; coingecko 20/60s; finnhub 50/60s; frankfurter 60/60s.
- Universe, verbatim: equities SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, JPM, XOM, JNJ, WMT. FRED DFF, DGS10, DGS2, T10Y2Y, CPIAUCSL, PCEPI, UNRATE, PAYEMS, GDPC1, M2SL, VIXCLS, MORTGAGE30US, INDPRO, HOUST, UMCSENT. Crypto top 20 by market cap. FX base EUR.
- Local test database: `postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test`.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/api/pyproject.toml` | Dependencies, pytest config, package metadata |
| `apps/api/src/marketpulse/config.py` | `Settings` — env-backed configuration |
| `apps/api/src/marketpulse/universe.py` | The symbol/series constants. Data only, no logic |
| `apps/api/src/marketpulse/core/ratelimit.py` | `Bucket`, `TokenBucket`, `DailyCapExceeded` |
| `apps/api/src/marketpulse/db/models.py` | SQLAlchemy declarative models |
| `apps/api/src/marketpulse/db/session.py` | Async engine + session factory |
| `apps/api/src/marketpulse/db/migrations/` | Alembic environment and versions |
| `apps/api/src/marketpulse/clients/base.py` | `BaseClient` — retry, rate limit, JSON fetch |
| `apps/api/src/marketpulse/clients/frankfurter.py` | `FxRate`, `FrankfurterClient` |
| `apps/api/src/marketpulse/clients/fred.py` | `FredSeriesMeta`, `FredObservation`, `FredClient` |
| `apps/api/src/marketpulse/clients/coingecko.py` | `CoinSnapshot`, `CoinHistoryPoint`, `CoinGeckoClient` |
| `apps/api/src/marketpulse/clients/alphavantage.py` | `DailyBar`, `AlphaVantageClient` |
| `apps/api/src/marketpulse/clients/finnhub.py` | `NewsItem`, `EarningsEvent`, `RatingSnapshot`, `FinnhubClient` |
| `apps/api/src/marketpulse/ingest/common.py` | `upsert_series`, `upsert_observations` — shared by fx/macro/crypto |
| `apps/api/src/marketpulse/ingest/runner.py` | `JobResult`, `run_job` — the `ingest_run` wrapper |
| `apps/api/src/marketpulse/ingest/fx.py` | `ingest_fx` |
| `apps/api/src/marketpulse/ingest/macro.py` | `ingest_macro` |
| `apps/api/src/marketpulse/ingest/crypto.py` | `ingest_crypto` |
| `apps/api/src/marketpulse/ingest/prices.py` | `ingest_prices` |
| `apps/api/src/marketpulse/ingest/news.py` | `ingest_news`, `ingest_earnings`, `ingest_ratings` |
| `apps/api/src/marketpulse/ingest/__main__.py` | Typer CLI — `backfill`, `daily` |

Split rationale: one file per vendor because vendor quirks change together and nothing else changes with them. `ingest/common.py` exists because three sources write the same two tables — without it that upsert logic would be copy-pasted three times.

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/marketpulse/__init__.py`
- Create: `apps/api/src/marketpulse/config.py`
- Create: `apps/api/src/marketpulse/universe.py`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Test: `apps/api/tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `Settings` with fields `database_url: str`, `alphavantage_api_key: str`, `fred_api_key: str`, `finnhub_api_key: str`, `ingest_hmac_secret: str`, `cors_origins: list[str]`. Module-level `get_settings() -> Settings` (cached). `universe.EQUITIES: tuple[str, ...]`, `universe.FRED_SERIES: tuple[str, ...]`, `universe.CRYPTO_LIMIT: int`, `universe.FX_BASE: str`, `universe.FX_START: date`.

- [ ] **Step 1: Create the directory skeleton and .gitignore**

```bash
mkdir -p apps/api/src/marketpulse/{clients,ingest,core,db}
mkdir -p apps/api/tests/fixtures
touch apps/api/src/marketpulse/__init__.py
touch apps/api/src/marketpulse/{clients,ingest,core,db}/__init__.py
touch apps/api/tests/__init__.py
```

`.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
.pytest_cache/
.ruff_cache/
dist/
node_modules/
```

- [ ] **Step 2: Write `apps/api/pyproject.toml`**

```toml
[project]
name = "marketpulse"
version = "0.1.0"
requires-python = "==3.12.*"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "httpx>=0.28",
    "tenacity>=9.0",
    "pydantic-settings>=2.6",
    "typer>=0.15",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.22",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/marketpulse"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 3: Write `docker-compose.yml` and `.env.example`**

`docker-compose.yml` at the repo root:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: marketpulse
      POSTGRES_PASSWORD: marketpulse
      POSTGRES_DB: marketpulse_test
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U marketpulse"]
      interval: 5s
      retries: 10
```

`.env.example` at the repo root — every key present, every value blank:

```dotenv
DATABASE_URL=
ALPHAVANTAGE_API_KEY=
FRED_API_KEY=
FINNHUB_API_KEY=
INGEST_HMAC_SECRET=
CORS_ORIGINS=
```

- [ ] **Step 4: Write the failing test**

`apps/api/tests/test_config.py`:

```python
from marketpulse.config import Settings
from marketpulse import universe


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.alphavantage_api_key == "av-key"
    assert settings.cors_origins == []


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key")
    monkeypatch.setenv("INGEST_HMAC_SECRET", "secret")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.dev,https://b.dev")

    assert Settings().cors_origins == ["https://a.dev", "https://b.dev"]


def test_universe_matches_spec():
    assert len(universe.EQUITIES) == 15
    assert "SPY" in universe.EQUITIES
    assert len(universe.FRED_SERIES) == 15
    assert "CPIAUCSL" in universe.FRED_SERIES
    assert universe.CRYPTO_LIMIT == 20
    assert universe.FX_BASE == "EUR"
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.config'`

- [ ] **Step 6: Write `config.py` and `universe.py`**

`apps/api/src/marketpulse/config.py`:

```python
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    alphavantage_api_key: str
    fred_api_key: str
    finnhub_api_key: str
    ingest_hmac_secret: str
    cors_origins: list[str] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`apps/api/src/marketpulse/universe.py`:

```python
from datetime import date

EQUITIES: tuple[str, ...] = (
    "SPY", "QQQ", "DIA", "IWM",
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    "TSLA", "JPM", "XOM", "JNJ", "WMT",
)

FRED_SERIES: tuple[str, ...] = (
    "DFF", "DGS10", "DGS2", "T10Y2Y",
    "CPIAUCSL", "PCEPI", "UNRATE", "PAYEMS", "GDPC1",
    "M2SL", "VIXCLS", "MORTGAGE30US", "INDPRO", "HOUST", "UMCSENT",
)

# FRED series id -> category used in the `series` table.
FRED_CATEGORY: dict[str, str] = {
    "DFF": "rates", "DGS10": "rates", "DGS2": "rates", "T10Y2Y": "rates",
    "MORTGAGE30US": "rates", "VIXCLS": "rates",
    "CPIAUCSL": "inflation", "PCEPI": "inflation",
    "UNRATE": "labor", "PAYEMS": "labor",
    "GDPC1": "growth", "M2SL": "growth", "INDPRO": "growth",
    "HOUST": "growth", "UMCSENT": "growth",
}

CRYPTO_LIMIT: int = 20

FX_BASE: str = "EUR"
FX_START: date = date(1999, 1, 4)  # first ECB reference rate date
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/test_config.py -v`
Expected: PASS, 3 tests

- [ ] **Step 8: Commit**

```bash
git add apps/api/pyproject.toml apps/api/src apps/api/tests docker-compose.yml .env.example .gitignore
git commit -m "feat: scaffold marketpulse package with config and universe"
```

---

### Task 2: Database models and Alembic baseline

**Files:**
- Create: `apps/api/src/marketpulse/db/models.py`
- Create: `apps/api/src/marketpulse/db/session.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/src/marketpulse/db/migrations/env.py`
- Create: `apps/api/tests/conftest.py`
- Test: `apps/api/tests/test_models.py`

**Interfaces:**
- Consumes: `Settings` from Task 1.
- Produces: `Base`, and models `Series`, `Observation`, `Asset`, `PriceDaily`, `News`, `EarningsCalendar`, `AnalystRating`, `IngestRun`. From `session.py`: `make_engine(url: str) -> AsyncEngine` and `make_session_factory(engine) -> async_sessionmaker[AsyncSession]`. Pytest fixtures `db_engine` and `db_session` (an `AsyncSession`, rolled back after each test).

- [ ] **Step 1: Confirm the local database is reachable**

PostgreSQL 16 runs here as a native Windows service on port 5433, already installed. Confirm the role and database exist, creating them if they do not. `psql` lives under `C:\Program Files\PostgreSQL\16\bin`; the `postgres` superuser password is `marketpulse`.

```bash
export PGPASSWORD=marketpulse
PSQL="/c/Program Files/PostgreSQL/16/bin/psql.exe"

"$PSQL" -U postgres -h localhost -p 5433 -c "\du" | grep -q marketpulse \
  || "$PSQL" -U postgres -h localhost -p 5433 \
       -c "CREATE ROLE marketpulse LOGIN PASSWORD 'marketpulse';"

"$PSQL" -U postgres -h localhost -p 5433 -lqt | cut -d'|' -f1 | grep -qw marketpulse_test \
  || "$PSQL" -U postgres -h localhost -p 5433 \
       -c "CREATE DATABASE marketpulse_test OWNER marketpulse;"

"$PSQL" -U marketpulse -h localhost -p 5433 -d marketpulse_test -c "SELECT 1;"
```

Expected: the final command prints a one-row result. `docker-compose.yml` stays committed for other machines but is not used here.

- [ ] **Step 2: Write the failing test**

`apps/api/tests/test_models.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from marketpulse.db.models import IngestRun, Observation, Series


async def test_series_and_observation_round_trip(db_session):
    series = Series(
        source="frankfurter", external_id="EUR/USD", name="Euro to US Dollar",
        unit="rate", frequency="D", category="fx",
    )
    db_session.add(series)
    await db_session.flush()

    db_session.add(Observation(series_id=series.id, obs_date=date(2024, 1, 2),
                               value=Decimal("1.0956")))
    await db_session.flush()

    stored = (await db_session.execute(select(Observation))).scalar_one()
    assert stored.value == Decimal("1.0956")
    assert stored.series_id == series.id


async def test_observation_value_is_nullable(db_session):
    series = Series(source="fred", external_id="CPIAUCSL", name="CPI",
                    unit="Index", frequency="M", category="inflation")
    db_session.add(series)
    await db_session.flush()

    db_session.add(Observation(series_id=series.id, obs_date=date(1947, 1, 1), value=None))
    await db_session.flush()

    assert (await db_session.execute(select(Observation))).scalar_one().value is None


async def test_series_source_external_id_is_unique(db_session):
    for _ in range(2):
        db_session.add(Series(source="fred", external_id="DFF", name="Fed Funds",
                              unit="Percent", frequency="D", category="rates"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_ingest_run_defaults_to_zero_counters(db_session):
    run = IngestRun(source="frankfurter", job="fx", status="running",
                    started_at=datetime.now(timezone.utc))
    db_session.add(run)
    await db_session.flush()

    assert run.rows_upserted == 0
    assert run.api_calls_used == 0
    assert run.finished_at is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.db.models'`

- [ ] **Step 4: Write `db/models.py`**

```python
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
```

- [ ] **Step 5: Write `db/session.py`**

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
```

- [ ] **Step 6: Write `tests/conftest.py`**

Each test runs inside a transaction that is rolled back, so tests never see each other's rows.

```python
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import Base
from marketpulse.db.session import make_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test",
)


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    connection = await db_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
def fixture_path():
    from pathlib import Path
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/test_models.py -v`
Expected: PASS, 4 tests

- [ ] **Step 8: Generate the Alembic baseline migration**

```bash
cd apps/api
uv run alembic init -t async src/marketpulse/db/migrations
```

Then edit `alembic.ini` to set `script_location = src/marketpulse/db/migrations` and leave `sqlalchemy.url` empty. In `src/marketpulse/db/migrations/env.py`, replace the `target_metadata = None` line and the URL lookup:

```python
from marketpulse.config import get_settings
from marketpulse.db.models import Base

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)
```

Generate and inspect:

```bash
DATABASE_URL=postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test \
ALPHAVANTAGE_API_KEY=x FRED_API_KEY=x FINNHUB_API_KEY=x INGEST_HMAC_SECRET=x \
uv run alembic revision --autogenerate -m "baseline schema"
```

Open the generated file under `src/marketpulse/db/migrations/versions/` and confirm it creates all eight tables. Autogenerate does not always emit the BRIN index — if `observation_date_brin` is missing, add it to `upgrade()`:

```python
op.create_index("observation_date_brin", "observation", ["obs_date"], postgresql_using="brin")
```

- [ ] **Step 9: Verify the migration round-trips**

```bash
cd apps/api
export DATABASE_URL=postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test
export ALPHAVANTAGE_API_KEY=x FRED_API_KEY=x FINNHUB_API_KEY=x INGEST_HMAC_SECRET=x
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
```

Expected: three clean runs, no traceback.

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/marketpulse/db apps/api/alembic.ini apps/api/tests
git commit -m "feat: add database models and alembic baseline migration"
```

---

### Task 3: Async token-bucket rate limiter

**Files:**
- Create: `apps/api/src/marketpulse/core/ratelimit.py`
- Test: `apps/api/tests/test_ratelimit.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Bucket(rate: int, per: float = 60.0, daily_cap: int | None = None)` frozen dataclass. `DailyCapExceeded(Exception)`. `TokenBucket(spec: Bucket, *, clock=time.monotonic, sleep=asyncio.sleep)` with `async acquire() -> None`, `set_daily_used(used: int) -> None`, and read-only property `calls_made: int`. Module constant `RATE_LIMITS: dict[str, Bucket]`.

The clock and sleep are injected so tests are deterministic and instant. The daily counter is *set* from outside rather than read from the database — that is what keeps this module free of database imports while still enforcing the Alpha Vantage cap.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_ratelimit.py`:

```python
import pytest

from marketpulse.core.ratelimit import Bucket, DailyCapExceeded, RATE_LIMITS, TokenBucket


class FakeClock:
    """Deterministic monotonic clock; sleeping advances it instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_acquire_is_free_while_tokens_remain():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=5, per=60.0), clock=clock.time, sleep=clock.sleep)

    for _ in range(5):
        await bucket.acquire()

    assert clock.slept == []
    assert bucket.calls_made == 5


async def test_acquire_sleeps_once_the_bucket_is_empty():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=2, per=60.0), clock=clock.time, sleep=clock.sleep)

    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()

    assert len(clock.slept) == 1
    assert clock.slept[0] == pytest.approx(30.0)  # per / rate


async def test_tokens_refill_over_time():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=2, per=60.0), clock=clock.time, sleep=clock.sleep)

    await bucket.acquire()
    await bucket.acquire()
    clock.now += 60.0
    await bucket.acquire()

    assert clock.slept == []


async def test_daily_cap_raises_once_exhausted():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=3),
                         clock=clock.time, sleep=clock.sleep)

    for _ in range(3):
        await bucket.acquire()

    with pytest.raises(DailyCapExceeded):
        await bucket.acquire()


async def test_set_daily_used_counts_against_the_cap():
    clock = FakeClock()
    bucket = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=25),
                         clock=clock.time, sleep=clock.sleep)
    bucket.set_daily_used(25)

    with pytest.raises(DailyCapExceeded):
        await bucket.acquire()


async def test_rate_limits_match_the_spec():
    assert RATE_LIMITS["alphavantage"] == Bucket(rate=5, per=60.0, daily_cap=25)
    assert RATE_LIMITS["fred"] == Bucket(rate=100, per=60.0)
    assert RATE_LIMITS["coingecko"] == Bucket(rate=20, per=60.0)
    assert RATE_LIMITS["finnhub"] == Bucket(rate=50, per=60.0)
    assert RATE_LIMITS["frankfurter"] == Bucket(rate=60, per=60.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ratelimit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.core.ratelimit'`

- [ ] **Step 3: Write `core/ratelimit.py`**

```python
import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable


class DailyCapExceeded(Exception):
    """Raised when a source's daily request budget is spent."""


@dataclass(frozen=True)
class Bucket:
    rate: int
    per: float = 60.0
    daily_cap: int | None = None


class TokenBucket:
    def __init__(
        self,
        spec: Bucket,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._spec = spec
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(spec.rate)
        self._updated = clock()
        self._daily_used = 0
        self._calls_made = 0
        self._lock = asyncio.Lock()

    @property
    def calls_made(self) -> int:
        return self._calls_made

    def set_daily_used(self, used: int) -> None:
        self._daily_used = used

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._updated
        self._updated = now
        refill = elapsed * (self._spec.rate / self._spec.per)
        self._tokens = min(float(self._spec.rate), self._tokens + refill)

    async def acquire(self) -> None:
        async with self._lock:
            cap = self._spec.daily_cap
            if cap is not None and self._daily_used >= cap:
                raise DailyCapExceeded(
                    f"daily cap of {cap} requests reached"
                )

            self._refill()
            if self._tokens < 1.0:
                await self._sleep(self._spec.per / self._spec.rate)
                self._refill()

            self._tokens -= 1.0
            self._daily_used += 1
            self._calls_made += 1


RATE_LIMITS: dict[str, Bucket] = {
    "alphavantage": Bucket(rate=5, per=60.0, daily_cap=25),
    "fred": Bucket(rate=100, per=60.0),
    "coingecko": Bucket(rate=20, per=60.0),
    "finnhub": Bucket(rate=50, per=60.0),
    "frankfurter": Bucket(rate=60, per=60.0),
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/test_ratelimit.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/marketpulse/core/ratelimit.py apps/api/tests/test_ratelimit.py
git commit -m "feat: add async token bucket rate limiter with daily cap"
```

---

### Task 4: HTTP client base with retry

**Files:**
- Create: `apps/api/src/marketpulse/clients/base.py`
- Test: `apps/api/tests/test_client_base.py`

**Interfaces:**
- Consumes: `TokenBucket`, `Bucket`, `RATE_LIMITS` from Task 3.
- Produces: `ApiError(Exception)`, `RateLimitedError(ApiError)`. `BaseClient(http: httpx.AsyncClient, limiter: TokenBucket)` with class attributes `source: str` and `base_url: str`, method `async get_json(path: str, params: dict | None = None) -> Any`, and property `calls_made: int`. Also `build_client(cls, *, http, limiter=None) -> BaseClient` is *not* provided — subclasses are constructed directly.

Retry policy, verbatim from the spec: exponential backoff, maximum 3 attempts, retrying only on 429, 5xx, and connection timeouts. Other 4xx fail immediately.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_client_base.py`:

```python
import httpx
import pytest
import respx

from marketpulse.clients.base import ApiError, BaseClient, RateLimitedError
from marketpulse.core.ratelimit import Bucket, TokenBucket


class DummyClient(BaseClient):
    source = "dummy"
    base_url = "https://example.test"


def make_client(http: httpx.AsyncClient) -> DummyClient:
    async def no_sleep(_: float) -> None:
        return None

    limiter = TokenBucket(Bucket(rate=1000, per=60.0), sleep=no_sleep)
    return DummyClient(http=http, limiter=limiter)


@respx.mock
async def test_get_json_returns_parsed_body():
    respx.get("https://example.test/thing").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_json("/thing") == {"ok": True}


@respx.mock
async def test_get_json_counts_one_call_per_request():
    respx.get("https://example.test/thing").mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.get_json("/thing")
        await client.get_json("/thing")
        assert client.calls_made == 2


@respx.mock
async def test_retries_on_500_then_succeeds():
    route = respx.get("https://example.test/thing").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_json("/thing") == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_three_attempts_and_raises_rate_limited():
    route = respx.get("https://example.test/thing").mock(return_value=httpx.Response(429))
    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError):
            await make_client(http).get_json("/thing")
    assert route.call_count == 3


@respx.mock
async def test_does_not_retry_on_404():
    route = respx.get("https://example.test/thing").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        with pytest.raises(ApiError):
            await make_client(http).get_json("/thing")
    assert route.call_count == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_client_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.clients.base'`

- [ ] **Step 3: Write `clients/base.py`**

```python
from typing import Any

import httpx
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from marketpulse.core.ratelimit import TokenBucket


class ApiError(Exception):
    """Any non-retryable failure from a vendor API."""


class RateLimitedError(ApiError):
    """The vendor rejected the request for rate-limit reasons."""


class TransientError(ApiError):
    """A failure worth retrying: 5xx or a timeout."""


_RETRYABLE = (RateLimitedError, TransientError, httpx.TimeoutException,
              httpx.ConnectError)


class BaseClient:
    source: str = "base"
    base_url: str = ""

    def __init__(self, http: httpx.AsyncClient, limiter: TokenBucket) -> None:
        self._http = http
        self._limiter = limiter

    @property
    def calls_made(self) -> int:
        return self._limiter.calls_made

    def _auth_params(self) -> dict[str, str]:
        """Subclasses add their API key here. Base clients need none."""
        return {}

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        merged = {**self._auth_params(), **(params or {})}

        @retry(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=8),
            reraise=True,
        )
        async def _attempt() -> Any:
            await self._limiter.acquire()
            response = await self._http.get(
                f"{self.base_url}{path}", params=merged, timeout=30.0
            )
            if response.status_code == 429:
                raise RateLimitedError(f"{self.source}: 429 on {path}")
            if response.status_code >= 500:
                raise TransientError(f"{self.source}: {response.status_code} on {path}")
            if response.status_code >= 400:
                raise ApiError(
                    f"{self.source}: {response.status_code} on {path} — {response.text[:200]}"
                )
            return response.json()

        return await _attempt()
```

Note: `wait_exponential` is used rather than honoring `Retry-After` here because none of the five vendors return that header on their free tiers. If one starts to, add a `RateLimitedError.retry_after` field and a custom `wait` callable.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/test_client_base.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/marketpulse/clients/base.py apps/api/tests/test_client_base.py
git commit -m "feat: add HTTP client base with rate limiting and retry"
```

---

### Task 5: Frankfurter client

**Files:**
- Create: `apps/api/src/marketpulse/clients/frankfurter.py`
- Create: `apps/api/tests/fixtures/frankfurter_timeseries.json`
- Test: `apps/api/tests/test_frankfurter_client.py`

**Interfaces:**
- Consumes: `BaseClient` from Task 4.
- Produces: `FxRate(base: str, quote: str, obs_date: date, rate: Decimal)` frozen dataclass. `FrankfurterClient(BaseClient)` with `source = "frankfurter"`, `base_url = "https://api.frankfurter.dev/v1"`, and `async fetch_timeseries(start: date, base: str = "EUR") -> list[FxRate]`.

Frankfurter returns the full date range in one request, which is why this is the first source: one call, no key, no pagination.

- [ ] **Step 1: Create the fixture**

`apps/api/tests/fixtures/frankfurter_timeseries.json`:

```json
{
  "amount": 1.0,
  "base": "EUR",
  "start_date": "2024-01-02",
  "end_date": "2024-01-03",
  "rates": {
    "2024-01-02": {"USD": 1.0956, "GBP": 0.86598, "JPY": 155.29},
    "2024-01-03": {"USD": 1.0919, "GBP": 0.86353, "JPY": 156.06}
  }
}
```

- [ ] **Step 2: Write the failing test**

`apps/api/tests/test_frankfurter_client.py`:

```python
import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.frankfurter import FrankfurterClient, FxRate
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> FrankfurterClient:
    async def no_sleep(_: float) -> None:
        return None

    return FrankfurterClient(http=http, limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_timeseries_flattens_nested_rates(fixture_path):
    payload = json.loads((fixture_path / "frankfurter_timeseries.json").read_text())
    respx.get(url__startswith="https://api.frankfurter.dev/v1/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        rates = await make_client(http).fetch_timeseries(date(2024, 1, 1))

    assert len(rates) == 6  # 2 dates x 3 currencies
    assert FxRate(base="EUR", quote="USD", obs_date=date(2024, 1, 2),
                  rate=Decimal("1.0956")) in rates


@respx.mock
async def test_fetch_timeseries_uses_one_request(fixture_path):
    payload = json.loads((fixture_path / "frankfurter_timeseries.json").read_text())
    route = respx.get(url__startswith="https://api.frankfurter.dev/v1/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.fetch_timeseries(date(1999, 1, 4))

    assert route.call_count == 1
    assert client.calls_made == 1


@respx.mock
async def test_rate_is_decimal_not_float(fixture_path):
    payload = json.loads((fixture_path / "frankfurter_timeseries.json").read_text())
    respx.get(url__startswith="https://api.frankfurter.dev/v1/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        rates = await make_client(http).fetch_timeseries(date(2024, 1, 1))

    assert all(isinstance(item.rate, Decimal) for item in rates)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_frankfurter_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.clients.frankfurter'`

- [ ] **Step 4: Write `clients/frankfurter.py`**

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from marketpulse.clients.base import BaseClient


@dataclass(frozen=True)
class FxRate:
    base: str
    quote: str
    obs_date: date
    rate: Decimal


class FrankfurterClient(BaseClient):
    source = "frankfurter"
    base_url = "https://api.frankfurter.dev/v1"

    async def fetch_timeseries(self, start: date, base: str = "EUR") -> list[FxRate]:
        payload = await self.get_json(f"/{start.isoformat()}..", params={"base": base})
        resolved_base = payload.get("base", base)

        rates: list[FxRate] = []
        for day, quotes in payload.get("rates", {}).items():
            obs_date = date.fromisoformat(day)
            for quote, value in quotes.items():
                rates.append(
                    FxRate(
                        base=resolved_base,
                        quote=quote,
                        obs_date=obs_date,
                        rate=Decimal(str(value)),
                    )
                )
        return rates
```

`Decimal(str(value))` rather than `Decimal(value)` — `json.loads` produces floats, and constructing a `Decimal` from a float carries the binary rounding error into the database.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/test_frankfurter_client.py -v`
Expected: PASS, 3 tests

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/marketpulse/clients/frankfurter.py apps/api/tests/test_frankfurter_client.py apps/api/tests/fixtures/frankfurter_timeseries.json
git commit -m "feat: add Frankfurter FX client"
```

---

### Task 6: Ingest runner and shared upsert helpers

**Files:**
- Create: `apps/api/src/marketpulse/ingest/runner.py`
- Create: `apps/api/src/marketpulse/ingest/common.py`
- Test: `apps/api/tests/test_ingest_runner.py`
- Test: `apps/api/tests/test_ingest_common.py`

**Interfaces:**
- Consumes: models from Task 2.
- Produces:
  - From `runner.py`: `JobResult(rows_upserted: int = 0, api_calls_used: int = 0, errors: list[str] = [])` dataclass, and `async run_job(session_factory, source: str, job: str, fn: Callable[[AsyncSession], Awaitable[JobResult]]) -> int` returning the `ingest_run.id`. Also `async calls_used_today(session, source: str) -> int`.
  - From `common.py`: `dedupe_by(rows: Sequence[dict], key: Callable[[dict], Hashable]) -> list[dict]`, `async upsert_series(session, *, source, external_id, name, unit, frequency, category) -> int` returning the series id, and `async upsert_observations(session, series_id: int, points: Iterable[tuple[date, Decimal | None]]) -> int` returning the row count.

**Why `dedupe_by` exists.** Postgres rejects a statement whose `ON CONFLICT DO UPDATE` would touch the same row twice: `ON CONFLICT DO UPDATE command cannot affect row a second time`. Both real sources trigger this. CoinGecko's `market_chart?days=max` appends a final current-time point that usually carries the same date as the last daily point. Finnhub returns overlapping news windows that can repeat a URL inside one response. Every batch insert in this codebase therefore passes through `dedupe_by` first, last occurrence winning.

Status rules, verbatim from the spec: exception before any write → `failed`; errors present but some rows written → `partial`; otherwise → `success`.

- [ ] **Step 1: Write the failing test for `common.py`**

`apps/api/tests/test_ingest_common.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.db.models import Observation, Series
from marketpulse.ingest.common import upsert_observations, upsert_series


async def test_upsert_series_creates_then_returns_same_id(db_session):
    first = await upsert_series(db_session, source="frankfurter", external_id="EUR/USD",
                                name="Euro to US Dollar", unit="rate",
                                frequency="D", category="fx")
    second = await upsert_series(db_session, source="frankfurter", external_id="EUR/USD",
                                 name="Euro to US Dollar (renamed)", unit="rate",
                                 frequency="D", category="fx")

    assert first == second
    count = (await db_session.execute(select(func.count()).select_from(Series))).scalar_one()
    assert count == 1


async def test_upsert_series_updates_mutable_metadata(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="DFF",
                                    name="Old name", unit="Percent",
                                    frequency="D", category="rates")
    await upsert_series(db_session, source="fred", external_id="DFF",
                        name="Federal Funds Effective Rate", unit="Percent",
                        frequency="D", category="rates")

    stored = await db_session.get(Series, series_id)
    assert stored.name == "Federal Funds Effective Rate"


async def test_upsert_observations_is_idempotent(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="DFF",
                                    name="Fed Funds", unit="Percent",
                                    frequency="D", category="rates")
    points = [(date(2024, 1, 1), Decimal("5.33")), (date(2024, 1, 2), Decimal("5.33"))]

    assert await upsert_observations(db_session, series_id, points) == 2
    assert await upsert_observations(db_session, series_id, points) == 2

    count = (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one()
    assert count == 2


async def test_upsert_observations_overwrites_a_revised_value(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="GDPC1",
                                    name="Real GDP", unit="Billions",
                                    frequency="Q", category="growth")
    await upsert_observations(db_session, series_id, [(date(2024, 1, 1), Decimal("100"))])
    await upsert_observations(db_session, series_id, [(date(2024, 1, 1), Decimal("101"))])

    stored = (await db_session.execute(select(Observation))).scalar_one()
    assert stored.value == Decimal("101")


async def test_upsert_observations_accepts_null_values(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="UNRATE",
                                    name="Unemployment", unit="Percent",
                                    frequency="M", category="labor")
    await upsert_observations(db_session, series_id, [(date(1947, 1, 1), None)])

    assert (await db_session.execute(select(Observation))).scalar_one().value is None


async def test_upsert_observations_with_no_points_writes_nothing(db_session):
    series_id = await upsert_series(db_session, source="fred", external_id="M2SL",
                                    name="M2", unit="Billions",
                                    frequency="M", category="growth")
    assert await upsert_observations(db_session, series_id, []) == 0


def test_dedupe_by_keeps_the_last_occurrence():
    rows = [{"k": 1, "v": "first"}, {"k": 2, "v": "other"}, {"k": 1, "v": "last"}]

    assert dedupe_by(rows, lambda row: row["k"]) == [
        {"k": 1, "v": "last"},
        {"k": 2, "v": "other"},
    ]


def test_dedupe_by_preserves_first_seen_order():
    rows = [{"k": 3}, {"k": 1}, {"k": 2}, {"k": 1}]

    assert [row["k"] for row in dedupe_by(rows, lambda row: row["k"])] == [3, 1, 2]


async def test_upsert_observations_survives_a_duplicated_date(db_session):
    """CoinGecko appends a current-time point that repeats the last daily date."""
    series_id = await upsert_series(db_session, source="coingecko",
                                    external_id="bitcoin:price", name="Bitcoin price",
                                    unit="USD", frequency="D", category="crypto")
    points = [
        (date(2024, 5, 1), Decimal("62000")),
        (date(2024, 5, 1), Decimal("62500")),  # same day, later snapshot
    ]

    assert await upsert_observations(db_session, series_id, points) == 1
    assert (await db_session.execute(select(Observation))).scalar_one().value == Decimal("62500")
```

The import line at the top of this file must include `dedupe_by`:

```python
from marketpulse.ingest.common import dedupe_by, upsert_observations, upsert_series
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.common'`

- [ ] **Step 3: Write `ingest/common.py`**

```python
from datetime import date
from decimal import Decimal
from typing import Callable, Hashable, Iterable, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import Observation, Series

# Postgres caps a statement at 65535 bind parameters; observation rows use 3 each.
_CHUNK = 5000


def dedupe_by(
    rows: Sequence[dict], key: Callable[[dict], Hashable]
) -> list[dict]:
    """Collapse rows sharing a conflict key, keeping the last occurrence.

    Postgres refuses an ON CONFLICT DO UPDATE statement that would touch the
    same row twice, so every batch insert filters through this first.
    """
    merged: dict[Hashable, dict] = {}
    for row in rows:
        merged[key(row)] = row
    return list(merged.values())


async def upsert_series(
    session: AsyncSession,
    *,
    source: str,
    external_id: str,
    name: str,
    unit: str | None,
    frequency: str | None,
    category: str,
) -> int:
    statement = (
        insert(Series)
        .values(source=source, external_id=external_id, name=name,
                unit=unit, frequency=frequency, category=category)
        .on_conflict_do_update(
            index_elements=[Series.source, Series.external_id],
            set_={"name": name, "unit": unit, "frequency": frequency, "category": category},
        )
        .returning(Series.id)
    )
    return (await session.execute(statement)).scalar_one()


async def upsert_observations(
    session: AsyncSession,
    series_id: int,
    points: Iterable[tuple[date, Decimal | None]],
) -> int:
    rows = dedupe_by(
        [
            {"series_id": series_id, "obs_date": obs_date, "value": value}
            for obs_date, value in points
        ],
        key=lambda row: row["obs_date"],
    )
    if not rows:
        return 0

    for start in range(0, len(rows), _CHUNK):
        chunk = rows[start:start + _CHUNK]
        statement = insert(Observation).values(chunk)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Observation.series_id, Observation.obs_date],
                set_={"value": statement.excluded.value},
            )
        )
    return len(rows)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_common.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Write the failing test for `runner.py`**

`apps/api/tests/test_ingest_runner.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from marketpulse.db.models import IngestRun
from marketpulse.ingest.runner import JobResult, calls_used_today, run_job


@pytest.fixture
def session_factory(db_session):
    """run_job asks for a session per run; hand it the transactional test session."""

    class _Factory:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return db_session

                async def __aexit__(self_inner, *exc):
                    return False

            return _Ctx()

    return _Factory()


async def test_successful_job_records_success(session_factory, db_session):
    async def job(session):
        return JobResult(rows_upserted=42, api_calls_used=1)

    run_id = await run_job(session_factory, "frankfurter", "fx", job)

    run = await db_session.get(IngestRun, run_id)
    assert run.status == "success"
    assert run.rows_upserted == 42
    assert run.api_calls_used == 1
    assert run.finished_at is not None
    assert run.error is None


async def test_job_with_errors_and_rows_records_partial(session_factory, db_session):
    async def job(session):
        return JobResult(rows_upserted=14, api_calls_used=15, errors=["TSLA: 404"])

    run_id = await run_job(session_factory, "alphavantage", "prices", job)

    run = await db_session.get(IngestRun, run_id)
    assert run.status == "partial"
    assert run.rows_upserted == 14
    assert "TSLA: 404" in run.error


async def test_raising_job_records_failed_and_reraises(session_factory, db_session):
    async def job(session):
        raise RuntimeError("bad api key")

    with pytest.raises(RuntimeError):
        await run_job(session_factory, "fred", "macro", job)

    run = (await db_session.execute(
        select(IngestRun).where(IngestRun.source == "fred"))).scalar_one()
    assert run.status == "failed"
    assert run.rows_upserted == 0
    assert "bad api key" in run.error


async def test_calls_used_today_sums_only_todays_runs(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all([
        IngestRun(source="alphavantage", job="prices", status="success",
                  started_at=now, api_calls_used=10),
        IngestRun(source="alphavantage", job="prices", status="success",
                  started_at=now - timedelta(days=2), api_calls_used=15),
        IngestRun(source="fred", job="macro", status="success",
                  started_at=now, api_calls_used=15),
    ])
    await db_session.flush()

    assert await calls_used_today(db_session, "alphavantage") == 10
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.runner'`

- [ ] **Step 7: Write `ingest/runner.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.db.models import IngestRun


@dataclass
class JobResult:
    rows_upserted: int = 0
    api_calls_used: int = 0
    errors: list[str] = field(default_factory=list)


async def calls_used_today(session: AsyncSession, source: str) -> int:
    statement = (
        select(func.coalesce(func.sum(IngestRun.api_calls_used), 0))
        .where(IngestRun.source == source)
        .where(func.date(IngestRun.started_at) == func.current_date())
    )
    return int((await session.execute(statement)).scalar_one())


async def run_job(
    session_factory,
    source: str,
    job: str,
    fn: Callable[[AsyncSession], Awaitable[JobResult]],
) -> int:
    async with session_factory() as session:
        run = IngestRun(source=source, job=job, status="running",
                        started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()

        try:
            result = await fn(session)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            await session.flush()
            await session.commit()
            raise

        run.rows_upserted = result.rows_upserted
        run.api_calls_used = result.api_calls_used
        run.error = "; ".join(result.errors)[:2000] if result.errors else None
        run.status = "partial" if result.errors else "success"
        run.finished_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()
        return run.id
```

Note on the failure path: the `ingest_run` row is committed before re-raising, so a crashed job still leaves an audit trail. The test session's outer transaction rolls the whole thing back afterwards, so `commit()` here is a savepoint release rather than a real commit under test.

- [ ] **Step 8: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_runner.py -v`
Expected: PASS, 4 tests

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/marketpulse/ingest apps/api/tests/test_ingest_runner.py apps/api/tests/test_ingest_common.py
git commit -m "feat: add ingest runner with audit trail and shared upsert helpers"
```

---

### Task 7: FX ingest job — the first end-to-end vertical slice

**Files:**
- Create: `apps/api/src/marketpulse/ingest/fx.py`
- Test: `apps/api/tests/test_ingest_fx.py`

**Interfaces:**
- Consumes: `FrankfurterClient`, `FxRate` (Task 5); `upsert_series`, `upsert_observations` (Task 6); `JobResult` (Task 6).
- Produces: `async ingest_fx(session: AsyncSession, client: FrankfurterClient, start: date) -> JobResult`.

Series naming convention, used by every later source: `external_id` is `"{BASE}/{QUOTE}"` for FX. Category is always `"fx"`.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_ingest_fx.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.clients.frankfurter import FxRate
from marketpulse.db.models import Observation, Series
from marketpulse.ingest.fx import ingest_fx

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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_fx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.fx'`

- [ ] **Step 3: Write `ingest/fx.py`**

```python
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.ingest.common import upsert_observations, upsert_series
from marketpulse.ingest.runner import JobResult


async def ingest_fx(session: AsyncSession, client, start: date) -> JobResult:
    rates = await client.fetch_timeseries(start)

    by_pair: dict[tuple[str, str], list[tuple[date, Decimal | None]]] = defaultdict(list)
    for item in rates:
        by_pair[(item.base, item.quote)].append((item.obs_date, item.rate))

    rows = 0
    for (base, quote), points in by_pair.items():
        series_id = await upsert_series(
            session,
            source="frankfurter",
            external_id=f"{base}/{quote}",
            name=f"{base} to {quote}",
            unit="rate",
            frequency="D",
            category="fx",
        )
        rows += await upsert_observations(session, series_id, points)

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_fx.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Run the whole suite**

Run: `cd apps/api && uv run pytest -v`
Expected: PASS, all tests. This is the first point where client → ingest → database works end to end.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/marketpulse/ingest/fx.py apps/api/tests/test_ingest_fx.py
git commit -m "feat: add FX ingest job"
```

---

### Task 8: FRED client and macro ingest

**Files:**
- Create: `apps/api/src/marketpulse/clients/fred.py`
- Create: `apps/api/src/marketpulse/ingest/macro.py`
- Create: `apps/api/tests/fixtures/fred_series.json`
- Create: `apps/api/tests/fixtures/fred_observations.json`
- Test: `apps/api/tests/test_fred_client.py`
- Test: `apps/api/tests/test_ingest_macro.py`

**Interfaces:**
- Consumes: `BaseClient` (Task 4), `upsert_series`/`upsert_observations` (Task 6), `JobResult` (Task 6), `universe.FRED_SERIES`/`universe.FRED_CATEGORY` (Task 1).
- Produces: `FredSeriesMeta(series_id: str, title: str, units: str, frequency: str)`, `FredObservation(obs_date: date, value: Decimal | None)`, `FredClient(BaseClient)` with `async fetch_series_meta(series_id) -> FredSeriesMeta` and `async fetch_observations(series_id, start: date | None = None) -> list[FredObservation]`. From `macro.py`: `async ingest_macro(session, client, series_ids: Sequence[str]) -> JobResult`.

FRED encodes a missing observation as the string `"."`. That maps to `None`, not to a dropped row — the spec requires gaps stay visible.

- [ ] **Step 1: Create the fixtures**

`apps/api/tests/fixtures/fred_series.json`:

```json
{
  "seriess": [
    {
      "id": "CPIAUCSL",
      "title": "Consumer Price Index for All Urban Consumers: All Items",
      "units": "Index 1982-1984=100",
      "frequency_short": "M",
      "seasonal_adjustment_short": "SA"
    }
  ]
}
```

`apps/api/tests/fixtures/fred_observations.json`:

```json
{
  "observations": [
    {"date": "2024-01-01", "value": "308.417"},
    {"date": "2024-02-01", "value": "310.326"},
    {"date": "2024-03-01", "value": "."}
  ]
}
```

- [ ] **Step 2: Write the failing client test**

`apps/api/tests/test_fred_client.py`:

```python
import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.fred import FredClient, FredObservation
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> FredClient:
    async def no_sleep(_: float) -> None:
        return None

    return FredClient(http=http, api_key="test-key",
                      limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_series_meta_maps_fields(fixture_path):
    payload = json.loads((fixture_path / "fred_series.json").read_text())
    respx.get("https://api.stlouisfed.org/fred/series").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        meta = await make_client(http).fetch_series_meta("CPIAUCSL")

    assert meta.series_id == "CPIAUCSL"
    assert meta.units == "Index 1982-1984=100"
    assert meta.frequency == "M"


@respx.mock
async def test_fetch_observations_maps_dot_to_none(fixture_path):
    payload = json.loads((fixture_path / "fred_observations.json").read_text())
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        observations = await make_client(http).fetch_observations("CPIAUCSL")

    assert len(observations) == 3
    assert observations[0] == FredObservation(date(2024, 1, 1), Decimal("308.417"))
    assert observations[2].value is None


@respx.mock
async def test_api_key_and_file_type_are_sent(fixture_path):
    payload = json.loads((fixture_path / "fred_observations.json").read_text())
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_observations("CPIAUCSL")

    request_url = route.calls[0].request.url
    assert request_url.params["api_key"] == "test-key"
    assert request_url.params["file_type"] == "json"
    assert request_url.params["series_id"] == "CPIAUCSL"


@respx.mock
async def test_start_date_becomes_observation_start(fixture_path):
    payload = json.loads((fixture_path / "fred_observations.json").read_text())
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_observations("CPIAUCSL", start=date(2024, 1, 1))

    assert route.calls[0].request.url.params["observation_start"] == "2024-01-01"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_fred_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.clients.fred'`

- [ ] **Step 4: Write `clients/fred.py`**

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from marketpulse.clients.base import ApiError, BaseClient
from marketpulse.core.ratelimit import TokenBucket


@dataclass(frozen=True)
class FredSeriesMeta:
    series_id: str
    title: str
    units: str
    frequency: str


@dataclass(frozen=True)
class FredObservation:
    obs_date: date
    value: Decimal | None


class FredClient(BaseClient):
    source = "fred"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, http: httpx.AsyncClient, api_key: str, limiter: TokenBucket) -> None:
        super().__init__(http=http, limiter=limiter)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        return {"api_key": self._api_key, "file_type": "json"}

    async def fetch_series_meta(self, series_id: str) -> FredSeriesMeta:
        payload = await self.get_json("/series", params={"series_id": series_id})
        entries = payload.get("seriess") or []
        if not entries:
            raise ApiError(f"fred: no metadata for series {series_id}")
        entry = entries[0]
        return FredSeriesMeta(
            series_id=entry["id"],
            title=entry["title"],
            units=entry.get("units", ""),
            frequency=entry.get("frequency_short", ""),
        )

    async def fetch_observations(
        self, series_id: str, start: date | None = None
    ) -> list[FredObservation]:
        params: dict[str, str] = {"series_id": series_id}
        if start is not None:
            params["observation_start"] = start.isoformat()

        payload = await self.get_json("/series/observations", params=params)
        return [
            FredObservation(date.fromisoformat(row["date"]), _to_decimal(row["value"]))
            for row in payload.get("observations", [])
        ]


def _to_decimal(raw: str) -> Decimal | None:
    """FRED writes a missing observation as '.'."""
    if raw in (".", "", None):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_fred_client.py -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Write the failing ingest test**

`apps/api/tests/test_ingest_macro.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.clients.fred import FredObservation, FredSeriesMeta
from marketpulse.db.models import Observation, Series
from marketpulse.ingest.macro import ingest_macro


class FakeFred:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls_made = 0

    async def fetch_series_meta(self, series_id: str) -> FredSeriesMeta:
        self.calls_made += 1
        if series_id in self.fail_on:
            raise RuntimeError(f"{series_id}: upstream 500")
        return FredSeriesMeta(series_id, f"Title for {series_id}", "Percent", "D")

    async def fetch_observations(self, series_id, start=None) -> list[FredObservation]:
        self.calls_made += 1
        return [
            FredObservation(date(2024, 1, 1), Decimal("5.33")),
            FredObservation(date(2024, 1, 2), None),
        ]


async def test_ingest_macro_writes_series_and_observations(db_session):
    result = await ingest_macro(db_session, FakeFred(), ["DFF", "UNRATE"])

    assert (await db_session.execute(
        select(func.count()).select_from(Series))).scalar_one() == 2
    assert (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one() == 4
    assert result.rows_upserted == 4
    assert result.errors == []


async def test_ingest_macro_uses_the_category_map(db_session):
    await ingest_macro(db_session, FakeFred(), ["DFF", "UNRATE"])

    rows = dict((await db_session.execute(
        select(Series.external_id, Series.category))).all())
    assert rows["DFF"] == "rates"
    assert rows["UNRATE"] == "labor"


async def test_one_failing_series_does_not_abort_the_others(db_session):
    result = await ingest_macro(db_session, FakeFred(fail_on={"DFF"}), ["DFF", "UNRATE"])

    assert (await db_session.execute(
        select(func.count()).select_from(Series))).scalar_one() == 1
    assert len(result.errors) == 1
    assert "DFF" in result.errors[0]
    assert result.rows_upserted == 2


async def test_ingest_macro_is_idempotent(db_session):
    await ingest_macro(db_session, FakeFred(), ["DFF"])
    await ingest_macro(db_session, FakeFred(), ["DFF"])

    assert (await db_session.execute(
        select(func.count()).select_from(Observation))).scalar_one() == 2


async def test_null_observations_are_stored_not_skipped(db_session):
    await ingest_macro(db_session, FakeFred(), ["DFF"])

    values = (await db_session.execute(
        select(Observation.value).order_by(Observation.obs_date))).scalars().all()
    assert values == [Decimal("5.33"), None]
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_macro.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.macro'`

- [ ] **Step 8: Write `ingest/macro.py`**

```python
from datetime import date
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.ingest.common import upsert_observations, upsert_series
from marketpulse.ingest.runner import JobResult
from marketpulse.universe import FRED_CATEGORY


async def ingest_macro(
    session: AsyncSession,
    client,
    series_ids: Sequence[str],
    start: date | None = None,
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for series_id in series_ids:
        try:
            meta = await client.fetch_series_meta(series_id)
            observations = await client.fetch_observations(series_id, start=start)

            internal_id = await upsert_series(
                session,
                source="fred",
                external_id=meta.series_id,
                name=meta.title,
                unit=meta.units,
                frequency=meta.frequency,
                category=FRED_CATEGORY.get(series_id, "other"),
            )
            rows += await upsert_observations(
                session, internal_id,
                [(item.obs_date, item.value) for item in observations],
            )
        except Exception as exc:
            errors.append(f"{series_id}: {exc}")

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
```

- [ ] **Step 9: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_macro.py -v`
Expected: PASS, 5 tests

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/marketpulse/clients/fred.py apps/api/src/marketpulse/ingest/macro.py apps/api/tests/test_fred_client.py apps/api/tests/test_ingest_macro.py apps/api/tests/fixtures/fred_series.json apps/api/tests/fixtures/fred_observations.json
git commit -m "feat: add FRED client and macro ingest job"
```

---

### Task 9: CoinGecko client and crypto ingest

**Files:**
- Create: `apps/api/src/marketpulse/clients/coingecko.py`
- Create: `apps/api/src/marketpulse/ingest/crypto.py`
- Create: `apps/api/tests/fixtures/coingecko_markets.json`
- Create: `apps/api/tests/fixtures/coingecko_market_chart.json`
- Test: `apps/api/tests/test_coingecko_client.py`
- Test: `apps/api/tests/test_ingest_crypto.py`

**Interfaces:**
- Consumes: `BaseClient` (Task 4), ingest helpers (Task 6), `universe.CRYPTO_LIMIT` (Task 1).
- Produces: `CoinSnapshot(coin_id, symbol, name, price_usd, market_cap_usd, volume_24h_usd, as_of: date)`, `CoinHistoryPoint(obs_date, price_usd, market_cap_usd, volume_24h_usd)`, `CoinGeckoClient(BaseClient)` with `async fetch_top_markets(limit: int = 20) -> list[CoinSnapshot]` and `async fetch_history(coin_id: str) -> list[CoinHistoryPoint]`. From `crypto.py`: `async ingest_crypto_snapshot(session, client, limit: int) -> JobResult` and `async ingest_crypto_history(session, client, coin_ids: Sequence[str]) -> JobResult`.

Each coin produces three series: `"{coin_id}:price"`, `"{coin_id}:market_cap"`, `"{coin_id}:volume"`. All categorised `"crypto"`.

The free tier does not accept the `interval` parameter on `market_chart`; granularity is chosen automatically and is daily for ranges beyond 90 days. Do not send `interval`.

- [ ] **Step 1: Create the fixtures**

`apps/api/tests/fixtures/coingecko_markets.json`:

```json
[
  {
    "id": "bitcoin", "symbol": "btc", "name": "Bitcoin",
    "current_price": 62500.12, "market_cap": 1231000000000,
    "total_volume": 28400000000, "last_updated": "2024-05-01T12:00:00.000Z"
  },
  {
    "id": "ethereum", "symbol": "eth", "name": "Ethereum",
    "current_price": 3010.44, "market_cap": 361000000000,
    "total_volume": 14200000000, "last_updated": "2024-05-01T12:00:00.000Z"
  }
]
```

`apps/api/tests/fixtures/coingecko_market_chart.json` (timestamps are epoch milliseconds, UTC):

```json
{
  "prices": [[1714521600000, 60000.5], [1714608000000, 62500.12]],
  "market_caps": [[1714521600000, 1180000000000], [1714608000000, 1231000000000]],
  "total_volumes": [[1714521600000, 25000000000], [1714608000000, 28400000000]]
}
```

- [ ] **Step 2: Write the failing client test**

`apps/api/tests/test_coingecko_client.py`:

```python
import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.coingecko import CoinGeckoClient
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> CoinGeckoClient:
    async def no_sleep(_: float) -> None:
        return None

    return CoinGeckoClient(http=http, limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_top_markets_maps_fields(fixture_path):
    payload = json.loads((fixture_path / "coingecko_markets.json").read_text())
    respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        coins = await make_client(http).fetch_top_markets(limit=2)

    assert [c.coin_id for c in coins] == ["bitcoin", "ethereum"]
    assert coins[0].market_cap_usd == Decimal("1231000000000")
    assert coins[0].as_of == date(2024, 5, 1)


@respx.mock
async def test_fetch_top_markets_requests_one_page(fixture_path):
    payload = json.loads((fixture_path / "coingecko_markets.json").read_text())
    route = respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.fetch_top_markets(limit=20)

    params = route.calls[0].request.url.params
    assert params["vs_currency"] == "usd"
    assert params["order"] == "market_cap_desc"
    assert params["per_page"] == "20"
    assert client.calls_made == 1


@respx.mock
async def test_fetch_history_zips_the_three_arrays(fixture_path):
    payload = json.loads((fixture_path / "coingecko_market_chart.json").read_text())
    respx.get(url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        points = await make_client(http).fetch_history("bitcoin")

    assert len(points) == 2
    assert points[0].obs_date == date(2024, 5, 1)
    assert points[1].price_usd == Decimal("62500.12")
    assert points[1].market_cap_usd == Decimal("1231000000000")


@respx.mock
async def test_fetch_history_does_not_send_the_interval_parameter(fixture_path):
    payload = json.loads((fixture_path / "coingecko_market_chart.json").read_text())
    route = respx.get(
        url__startswith="https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    ).mock(return_value=httpx.Response(200, json=payload))

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_history("bitcoin")

    params = route.calls[0].request.url.params
    assert "interval" not in params
    assert params["days"] == "max"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_coingecko_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.clients.coingecko'`

- [ ] **Step 4: Write `clients/coingecko.py`**

```python
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from marketpulse.clients.base import BaseClient


@dataclass(frozen=True)
class CoinSnapshot:
    coin_id: str
    symbol: str
    name: str
    price_usd: Decimal
    market_cap_usd: Decimal
    volume_24h_usd: Decimal
    as_of: date


@dataclass(frozen=True)
class CoinHistoryPoint:
    obs_date: date
    price_usd: Decimal
    market_cap_usd: Decimal
    volume_24h_usd: Decimal


def _dec(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _day(epoch_ms: int) -> date:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).date()


class CoinGeckoClient(BaseClient):
    source = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"

    async def fetch_top_markets(self, limit: int = 20) -> list[CoinSnapshot]:
        payload = await self.get_json(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": str(limit),
                "page": "1",
            },
        )
        return [
            CoinSnapshot(
                coin_id=row["id"],
                symbol=row["symbol"],
                name=row["name"],
                price_usd=_dec(row.get("current_price")),
                market_cap_usd=_dec(row.get("market_cap")),
                volume_24h_usd=_dec(row.get("total_volume")),
                as_of=datetime.fromisoformat(
                    row["last_updated"].replace("Z", "+00:00")
                ).date(),
            )
            for row in payload
        ]

    async def fetch_history(self, coin_id: str) -> list[CoinHistoryPoint]:
        # No `interval` parameter: it is a paid-tier option, and the free tier
        # already returns daily granularity for ranges beyond 90 days.
        payload = await self.get_json(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": "max"},
        )

        caps = {ts: value for ts, value in payload.get("market_caps", [])}
        volumes = {ts: value for ts, value in payload.get("total_volumes", [])}

        return [
            CoinHistoryPoint(
                obs_date=_day(ts),
                price_usd=_dec(price),
                market_cap_usd=_dec(caps.get(ts)),
                volume_24h_usd=_dec(volumes.get(ts)),
            )
            for ts, price in payload.get("prices", [])
        ]
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_coingecko_client.py -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Write the failing ingest test**

`apps/api/tests/test_ingest_crypto.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.clients.coingecko import CoinHistoryPoint, CoinSnapshot
from marketpulse.db.models import Observation, Series
from marketpulse.ingest.crypto import ingest_crypto_history, ingest_crypto_snapshot

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
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls_made = 0

    async def fetch_top_markets(self, limit: int = 20) -> list[CoinSnapshot]:
        self.calls_made += 1
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
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.crypto'`

- [ ] **Step 8: Write `ingest/crypto.py`**

```python
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.ingest.common import upsert_observations, upsert_series
from marketpulse.ingest.runner import JobResult

METRICS = ("price", "market_cap", "volume")
_UNITS = {"price": "USD", "market_cap": "USD", "volume": "USD"}


async def _series_id(session: AsyncSession, coin_id: str, name: str, metric: str) -> int:
    return await upsert_series(
        session,
        source="coingecko",
        external_id=f"{coin_id}:{metric}",
        name=f"{name} {metric.replace('_', ' ')}",
        unit=_UNITS[metric],
        frequency="D",
        category="crypto",
    )


async def ingest_crypto_snapshot(session: AsyncSession, client, limit: int) -> JobResult:
    coins = await client.fetch_top_markets(limit=limit)

    rows = 0
    for coin in coins:
        values = {
            "price": coin.price_usd,
            "market_cap": coin.market_cap_usd,
            "volume": coin.volume_24h_usd,
        }
        for metric in METRICS:
            series_id = await _series_id(session, coin.coin_id, coin.name, metric)
            rows += await upsert_observations(
                session, series_id, [(coin.as_of, values[metric])]
            )

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made)


async def ingest_crypto_history(
    session: AsyncSession, client, coin_ids: Sequence[str]
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for coin_id in coin_ids:
        try:
            points = await client.fetch_history(coin_id)
            by_metric = {
                "price": [(p.obs_date, p.price_usd) for p in points],
                "market_cap": [(p.obs_date, p.market_cap_usd) for p in points],
                "volume": [(p.obs_date, p.volume_24h_usd) for p in points],
            }
            for metric in METRICS:
                series_id = await _series_id(session, coin_id, coin_id, metric)
                rows += await upsert_observations(session, series_id, by_metric[metric])
        except Exception as exc:
            errors.append(f"{coin_id}: {exc}")

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
```

- [ ] **Step 9: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_crypto.py -v`
Expected: PASS, 6 tests

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/marketpulse/clients/coingecko.py apps/api/src/marketpulse/ingest/crypto.py apps/api/tests/test_coingecko_client.py apps/api/tests/test_ingest_crypto.py apps/api/tests/fixtures/coingecko_markets.json apps/api/tests/fixtures/coingecko_market_chart.json
git commit -m "feat: add CoinGecko client and crypto ingest jobs"
```

---

### Task 10: Alpha Vantage client and price ingest

**Files:**
- Create: `apps/api/src/marketpulse/clients/alphavantage.py`
- Create: `apps/api/src/marketpulse/ingest/prices.py`
- Create: `apps/api/tests/fixtures/alphavantage_daily.json`
- Create: `apps/api/tests/fixtures/alphavantage_ratelimit.json`
- Test: `apps/api/tests/test_alphavantage_client.py`
- Test: `apps/api/tests/test_ingest_prices.py`

**Interfaces:**
- Consumes: `BaseClient` (Task 4), `RateLimitedError` (Task 4), models `Asset`/`PriceDaily` (Task 2), `JobResult` (Task 6).
- Produces: `DailyBar(trade_date: date, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: int)`, `AlphaVantageClient(BaseClient)` with `async fetch_daily(symbol: str, full: bool = False) -> list[DailyBar]`. From `prices.py`: `async upsert_asset(session, symbol: str) -> int` and `async ingest_prices(session, client, symbols: Sequence[str], full: bool = False) -> JobResult`.

Alpha Vantage signals a rate-limit refusal with HTTP 200 and a body containing a `Note` or `Information` key. That must be detected and raised as `RateLimitedError`, otherwise the parser sees an empty time series and silently writes nothing.

- [ ] **Step 1: Create the fixtures**

`apps/api/tests/fixtures/alphavantage_daily.json`:

```json
{
  "Meta Data": {
    "1. Information": "Daily Prices (open, high, low, close) and Volumes",
    "2. Symbol": "AAPL",
    "3. Last Refreshed": "2024-05-01"
  },
  "Time Series (Daily)": {
    "2024-05-01": {
      "1. open": "169.5800", "2. high": "172.7050", "3. low": "169.1100",
      "4. close": "169.3000", "5. volume": "50383147"
    },
    "2024-04-30": {
      "1. open": "173.3300", "2. high": "174.9900", "3. low": "170.0000",
      "4. close": "170.3300", "5. volume": "65934787"
    }
  }
}
```

`apps/api/tests/fixtures/alphavantage_ratelimit.json`:

```json
{
  "Information": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."
}
```

- [ ] **Step 2: Write the failing client test**

`apps/api/tests/test_alphavantage_client.py`:

```python
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from marketpulse.clients.alphavantage import AlphaVantageClient
from marketpulse.clients.base import RateLimitedError
from marketpulse.core.ratelimit import Bucket, DailyCapExceeded, TokenBucket


def make_client(http: httpx.AsyncClient, limiter: TokenBucket | None = None):
    async def no_sleep(_: float) -> None:
        return None

    return AlphaVantageClient(
        http=http,
        api_key="test-key",
        limiter=limiter or TokenBucket(Bucket(rate=1000), sleep=no_sleep),
    )


@respx.mock
async def test_fetch_daily_returns_bars_in_ascending_date_order(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_daily.json").read_text())
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        bars = await make_client(http).fetch_daily("AAPL")

    assert [b.trade_date for b in bars] == [date(2024, 4, 30), date(2024, 5, 1)]
    assert bars[1].close == Decimal("169.3000")
    assert bars[1].volume == 50383147


@respx.mock
async def test_full_flag_switches_outputsize(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_daily.json").read_text())
    route = respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.fetch_daily("AAPL", full=False)
        await client.fetch_daily("AAPL", full=True)

    assert route.calls[0].request.url.params["outputsize"] == "compact"
    assert route.calls[1].request.url.params["outputsize"] == "full"
    assert route.calls[0].request.url.params["function"] == "TIME_SERIES_DAILY"
    assert route.calls[0].request.url.params["apikey"] == "test-key"


@respx.mock
async def test_rate_limit_note_in_a_200_body_raises(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_ratelimit.json").read_text())
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitedError):
            await make_client(http).fetch_daily("AAPL")


@respx.mock
async def test_daily_cap_stops_requests_before_they_are_sent(fixture_path):
    payload = json.loads((fixture_path / "alphavantage_daily.json").read_text())
    route = respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async def no_sleep(_: float) -> None:
        return None

    limiter = TokenBucket(Bucket(rate=100, per=60.0, daily_cap=25), sleep=no_sleep)
    limiter.set_daily_used(25)

    async with httpx.AsyncClient() as http:
        with pytest.raises(DailyCapExceeded):
            await make_client(http, limiter).fetch_daily("AAPL")

    assert route.call_count == 0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_alphavantage_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.clients.alphavantage'`

- [ ] **Step 4: Write `clients/alphavantage.py`**

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from marketpulse.clients.base import ApiError, BaseClient, RateLimitedError
from marketpulse.core.ratelimit import TokenBucket

_SERIES_KEY = "Time Series (Daily)"


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class AlphaVantageClient(BaseClient):
    source = "alphavantage"
    base_url = "https://www.alphavantage.co"

    def __init__(self, http: httpx.AsyncClient, api_key: str, limiter: TokenBucket) -> None:
        super().__init__(http=http, limiter=limiter)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        return {"apikey": self._api_key}

    async def fetch_daily(self, symbol: str, full: bool = False) -> list[DailyBar]:
        payload = await self.get_json(
            "/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "full" if full else "compact",
            },
        )

        # Alpha Vantage answers a throttled request with HTTP 200 and a prose body.
        if "Note" in payload or "Information" in payload:
            raise RateLimitedError(
                f"alphavantage: {payload.get('Note') or payload.get('Information')}"
            )
        if "Error Message" in payload:
            raise ApiError(f"alphavantage: {payload['Error Message']}")
        if _SERIES_KEY not in payload:
            raise ApiError(f"alphavantage: unexpected payload keys {sorted(payload)}")

        bars = [
            DailyBar(
                trade_date=date.fromisoformat(day),
                open=Decimal(row["1. open"]),
                high=Decimal(row["2. high"]),
                low=Decimal(row["3. low"]),
                close=Decimal(row["4. close"]),
                volume=int(row["5. volume"]),
            )
            for day, row in payload[_SERIES_KEY].items()
        ]
        bars.sort(key=lambda bar: bar.trade_date)
        return bars
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_alphavantage_client.py -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Write the failing ingest test**

`apps/api/tests/test_ingest_prices.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.clients.alphavantage import DailyBar
from marketpulse.core.ratelimit import DailyCapExceeded
from marketpulse.db.models import Asset, PriceDaily
from marketpulse.ingest.prices import ingest_prices, upsert_asset

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
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_prices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.prices'`

- [ ] **Step 8: Write `ingest/prices.py`**

```python
from typing import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.core.ratelimit import DailyCapExceeded
from marketpulse.db.models import Asset, PriceDaily
from marketpulse.ingest.runner import JobResult


async def upsert_asset(session: AsyncSession, symbol: str, name: str | None = None) -> int:
    statement = (
        insert(Asset)
        .values(symbol=symbol, name=name or symbol)
        .on_conflict_do_update(index_elements=[Asset.symbol], set_={"symbol": symbol})
        .returning(Asset.id)
    )
    return (await session.execute(statement)).scalar_one()


async def ingest_prices(
    session: AsyncSession, client, symbols: Sequence[str], full: bool = False
) -> JobResult:
    rows = 0
    errors: list[str] = []

    for symbol in symbols:
        try:
            bars = await client.fetch_daily(symbol, full=full)
        except DailyCapExceeded as exc:
            # The budget is gone for the day. Stop rather than burn retries.
            errors.append(f"{symbol}: {exc}")
            break
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        asset_id = await upsert_asset(session, symbol)
        payload = [
            {
                "asset_id": asset_id, "trade_date": bar.trade_date,
                "open": bar.open, "high": bar.high, "low": bar.low,
                "close": bar.close, "volume": bar.volume,
            }
            for bar in bars
        ]
        if not payload:
            continue

        statement = insert(PriceDaily).values(payload)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[PriceDaily.asset_id, PriceDaily.trade_date],
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "volume": statement.excluded.volume,
                },
            )
        )
        rows += len(payload)

    return JobResult(rows_upserted=rows, api_calls_used=client.calls_made, errors=errors)
```

- [ ] **Step 9: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_prices.py -v`
Expected: PASS, 7 tests

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/marketpulse/clients/alphavantage.py apps/api/src/marketpulse/ingest/prices.py apps/api/tests/test_alphavantage_client.py apps/api/tests/test_ingest_prices.py apps/api/tests/fixtures/alphavantage_daily.json apps/api/tests/fixtures/alphavantage_ratelimit.json
git commit -m "feat: add Alpha Vantage client and price ingest with daily cap handling"
```

---

### Task 11: Finnhub client and news, earnings, ratings ingest

**Files:**
- Create: `apps/api/src/marketpulse/clients/finnhub.py`
- Create: `apps/api/src/marketpulse/ingest/news.py`
- Create: `apps/api/tests/fixtures/finnhub_news.json`
- Create: `apps/api/tests/fixtures/finnhub_earnings.json`
- Create: `apps/api/tests/fixtures/finnhub_ratings.json`
- Test: `apps/api/tests/test_finnhub_client.py`
- Test: `apps/api/tests/test_ingest_news.py`

**Interfaces:**
- Consumes: `BaseClient` (Task 4), models `News`/`EarningsCalendar`/`AnalystRating` (Task 2), `JobResult` (Task 6).
- Produces: `NewsItem(symbol, published_at: datetime, headline, source, url, summary, image_url)`, `EarningsEvent(symbol, report_date, hour, eps_estimate, eps_actual, revenue_estimate, revenue_actual)`, `RatingSnapshot(symbol, period: date, strong_buy, buy, hold, sell, strong_sell)`, `FinnhubClient(BaseClient)` with `async fetch_news(symbol, start: date, end: date)`, `async fetch_earnings(start: date, end: date)`, `async fetch_ratings(symbol)`. From `news.py`: `async ingest_news(session, client, symbols, start, end) -> JobResult`, `async ingest_earnings(session, client, start, end) -> JobResult`, `async ingest_ratings(session, client, symbols) -> JobResult`.

Finnhub returns overlapping news windows across polls, so `news.url` is the conflict target. Duplicate URLs update the existing row rather than inserting.

- [ ] **Step 1: Create the fixtures**

`apps/api/tests/fixtures/finnhub_news.json`:

```json
[
  {
    "category": "company", "datetime": 1714579200, "headline": "Apple beats estimates",
    "id": 7712345, "image": "https://img.test/a.jpg", "related": "AAPL",
    "source": "Reuters", "summary": "Quarterly results topped forecasts.",
    "url": "https://news.test/apple-beats"
  },
  {
    "category": "company", "datetime": 1714492800, "headline": "Apple announces buyback",
    "id": 7712300, "image": "", "related": "AAPL",
    "source": "Bloomberg", "summary": "Board approved a repurchase programme.",
    "url": "https://news.test/apple-buyback"
  }
]
```

`apps/api/tests/fixtures/finnhub_earnings.json`:

```json
{
  "earningsCalendar": [
    {
      "date": "2024-05-02", "epsActual": 1.53, "epsEstimate": 1.5,
      "hour": "amc", "quarter": 2, "revenueActual": 90753000000,
      "revenueEstimate": 90005000000, "symbol": "AAPL", "year": 2024
    },
    {
      "date": "2024-05-09", "epsActual": null, "epsEstimate": 2.02,
      "hour": "bmo", "quarter": 2, "revenueActual": null,
      "revenueEstimate": 61000000000, "symbol": "MSFT", "year": 2024
    }
  ]
}
```

`apps/api/tests/fixtures/finnhub_ratings.json`:

```json
[
  {"buy": 24, "hold": 7, "period": "2024-05-01", "sell": 0,
   "strongBuy": 13, "strongSell": 0, "symbol": "AAPL"},
  {"buy": 22, "hold": 9, "period": "2024-04-01", "sell": 1,
   "strongBuy": 12, "strongSell": 0, "symbol": "AAPL"}
]
```

- [ ] **Step 2: Write the failing client test**

`apps/api/tests/test_finnhub_client.py`:

```python
import json
from datetime import date, timezone
from decimal import Decimal

import httpx
import respx

from marketpulse.clients.finnhub import FinnhubClient
from marketpulse.core.ratelimit import Bucket, TokenBucket


def make_client(http: httpx.AsyncClient) -> FinnhubClient:
    async def no_sleep(_: float) -> None:
        return None

    return FinnhubClient(http=http, api_key="test-key",
                         limiter=TokenBucket(Bucket(rate=1000), sleep=no_sleep))


@respx.mock
async def test_fetch_news_maps_epoch_to_utc_datetime(fixture_path):
    payload = json.loads((fixture_path / "finnhub_news.json").read_text())
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        items = await make_client(http).fetch_news(
            "AAPL", date(2024, 4, 25), date(2024, 5, 2)
        )

    assert len(items) == 2
    assert items[0].symbol == "AAPL"
    assert items[0].published_at.tzinfo is timezone.utc
    assert items[0].url == "https://news.test/apple-beats"
    assert items[1].image_url is None  # empty string normalises to None


@respx.mock
async def test_fetch_news_sends_the_token_and_window(fixture_path):
    payload = json.loads((fixture_path / "finnhub_news.json").read_text())
    route = respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        await make_client(http).fetch_news("AAPL", date(2024, 4, 25), date(2024, 5, 2))

    params = route.calls[0].request.url.params
    assert params["token"] == "test-key"
    assert params["symbol"] == "AAPL"
    assert params["from"] == "2024-04-25"
    assert params["to"] == "2024-05-02"


@respx.mock
async def test_fetch_earnings_handles_null_actuals(fixture_path):
    payload = json.loads((fixture_path / "finnhub_earnings.json").read_text())
    respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        events = await make_client(http).fetch_earnings(date(2024, 5, 1), date(2024, 5, 14))

    assert len(events) == 2
    assert events[0].eps_actual == Decimal("1.53")
    assert events[1].eps_actual is None
    assert events[1].revenue_estimate == 61000000000


@respx.mock
async def test_fetch_ratings_maps_camel_case_fields(fixture_path):
    payload = json.loads((fixture_path / "finnhub_ratings.json").read_text())
    respx.get("https://finnhub.io/api/v1/stock/recommendation").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as http:
        ratings = await make_client(http).fetch_ratings("AAPL")

    assert ratings[0].period == date(2024, 5, 1)
    assert ratings[0].strong_buy == 13
    assert ratings[0].strong_sell == 0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_finnhub_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.clients.finnhub'`

- [ ] **Step 4: Write `clients/finnhub.py`**

```python
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from marketpulse.clients.base import BaseClient
from marketpulse.core.ratelimit import TokenBucket


@dataclass(frozen=True)
class NewsItem:
    symbol: str
    published_at: datetime
    headline: str
    source: str | None
    url: str
    summary: str | None
    image_url: str | None


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    report_date: date
    hour: str | None
    eps_estimate: Decimal | None
    eps_actual: Decimal | None
    revenue_estimate: int | None
    revenue_actual: int | None


@dataclass(frozen=True)
class RatingSnapshot:
    symbol: str
    period: date
    strong_buy: int | None
    buy: int | None
    hold: int | None
    sell: int | None
    strong_sell: int | None


def _blank_to_none(value: str | None) -> str | None:
    return value or None


def _dec_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(value)


class FinnhubClient(BaseClient):
    source = "finnhub"
    base_url = "https://finnhub.io/api/v1"

    def __init__(self, http: httpx.AsyncClient, api_key: str, limiter: TokenBucket) -> None:
        super().__init__(http=http, limiter=limiter)
        self._api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        return {"token": self._api_key}

    async def fetch_news(self, symbol: str, start: date, end: date) -> list[NewsItem]:
        payload = await self.get_json(
            "/company-news",
            params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
        )
        return [
            NewsItem(
                symbol=symbol,
                published_at=datetime.fromtimestamp(row["datetime"], tz=timezone.utc),
                headline=row["headline"],
                source=_blank_to_none(row.get("source")),
                url=row["url"],
                summary=_blank_to_none(row.get("summary")),
                image_url=_blank_to_none(row.get("image")),
            )
            for row in payload
            if row.get("url")
        ]

    async def fetch_earnings(self, start: date, end: date) -> list[EarningsEvent]:
        payload = await self.get_json(
            "/calendar/earnings",
            params={"from": start.isoformat(), "to": end.isoformat()},
        )
        return [
            EarningsEvent(
                symbol=row["symbol"],
                report_date=date.fromisoformat(row["date"]),
                hour=_blank_to_none(row.get("hour")),
                eps_estimate=_dec_or_none(row.get("epsEstimate")),
                eps_actual=_dec_or_none(row.get("epsActual")),
                revenue_estimate=_int_or_none(row.get("revenueEstimate")),
                revenue_actual=_int_or_none(row.get("revenueActual")),
            )
            for row in payload.get("earningsCalendar", [])
        ]

    async def fetch_ratings(self, symbol: str) -> list[RatingSnapshot]:
        payload = await self.get_json("/stock/recommendation", params={"symbol": symbol})
        return [
            RatingSnapshot(
                symbol=row["symbol"],
                period=date.fromisoformat(row["period"]),
                strong_buy=_int_or_none(row.get("strongBuy")),
                buy=_int_or_none(row.get("buy")),
                hold=_int_or_none(row.get("hold")),
                sell=_int_or_none(row.get("sell")),
                strong_sell=_int_or_none(row.get("strongSell")),
            )
            for row in payload
        ]
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_finnhub_client.py -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Write the failing ingest test**

`apps/api/tests/test_ingest_news.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from marketpulse.clients.finnhub import EarningsEvent, NewsItem, RatingSnapshot
from marketpulse.db.models import AnalystRating, EarningsCalendar, News
from marketpulse.ingest.news import ingest_earnings, ingest_news, ingest_ratings

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
    result = await ingest_earnings(db_session, FakeFinnhub(),
                                   date(2024, 5, 1), date(2024, 5, 14))

    assert result.rows_upserted == 2
    msft = await db_session.get(EarningsCalendar, ("MSFT", date(2024, 5, 9)))
    assert msft.eps_actual is None
    assert msft.eps_estimate == Decimal("2.02")


async def test_earnings_rerun_updates_actuals_in_place(db_session):
    await ingest_earnings(db_session, FakeFinnhub(), date(2024, 5, 1), date(2024, 5, 14))
    await ingest_earnings(db_session, FakeFinnhub(), date(2024, 5, 1), date(2024, 5, 14))

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
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_news.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.news'`

- [ ] **Step 8: Write `ingest/news.py`**

```python
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
```

- [ ] **Step 9: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_news.py -v`
Expected: PASS, 8 tests

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/marketpulse/clients/finnhub.py apps/api/src/marketpulse/ingest/news.py apps/api/tests/test_finnhub_client.py apps/api/tests/test_ingest_news.py apps/api/tests/fixtures/finnhub_news.json apps/api/tests/fixtures/finnhub_earnings.json apps/api/tests/fixtures/finnhub_ratings.json
git commit -m "feat: add Finnhub client and news, earnings, ratings ingest"
```

---

### Task 12: Job registry and backfill CLI

**Files:**
- Create: `apps/api/src/marketpulse/ingest/jobs.py`
- Create: `apps/api/src/marketpulse/ingest/__main__.py`
- Test: `apps/api/tests/test_ingest_jobs.py`

**Interfaces:**
- Consumes: every client and ingest job from Tasks 5 and 8–11; `run_job`/`calls_used_today` (Task 6); `RATE_LIMITS`/`TokenBucket` (Task 3); `Settings` (Task 1); `universe` (Task 1).
- Produces: `async build_client(source: str, http: httpx.AsyncClient, session: AsyncSession, settings: Settings)` returning a configured client with its daily-used counter seeded. `JOB_NAMES: tuple[str, ...]` = `("prices", "macro", "crypto", "news", "earnings", "ratings", "fx")`. `async run_source(source_or_job: str, *, full: bool, session_factory, settings) -> int` returning the `ingest_run.id`. A Typer app exposing `backfill` and `daily`.

This is the task that connects the daily cap to the database: `build_client` calls `calls_used_today` and feeds the result into `TokenBucket.set_daily_used`. Neither the client nor the limiter imports anything from `db/` — the wiring happens here.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_ingest_jobs.py`:

```python
from datetime import datetime, timezone

import httpx
import pytest

from marketpulse.config import Settings
from marketpulse.db.models import IngestRun
from marketpulse.ingest.jobs import JOB_NAMES, build_client, job_source


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        alphavantage_api_key="av", fred_api_key="fred",
        finnhub_api_key="fh", ingest_hmac_secret="secret",
    )


def test_job_names_cover_every_scheduled_job():
    assert JOB_NAMES == ("prices", "macro", "crypto", "news", "earnings", "ratings", "fx")


def test_each_job_maps_to_its_source():
    assert job_source("prices") == "alphavantage"
    assert job_source("macro") == "fred"
    assert job_source("crypto") == "coingecko"
    assert job_source("news") == "finnhub"
    assert job_source("earnings") == "finnhub"
    assert job_source("ratings") == "finnhub"
    assert job_source("fx") == "frankfurter"


def test_unknown_job_name_raises():
    with pytest.raises(KeyError):
        job_source("nonsense")


async def test_build_client_seeds_the_daily_counter_from_the_database(
    db_session, settings
):
    db_session.add(IngestRun(source="alphavantage", job="prices", status="success",
                             started_at=datetime.now(timezone.utc), api_calls_used=20))
    await db_session.flush()

    async with httpx.AsyncClient() as http:
        client = await build_client("alphavantage", http, db_session, settings)

    # 5 of the 25-request budget remain.
    for _ in range(5):
        await client._limiter.acquire()

    from marketpulse.core.ratelimit import DailyCapExceeded
    with pytest.raises(DailyCapExceeded):
        await client._limiter.acquire()


async def test_build_client_returns_the_right_class_per_source(db_session, settings):
    from marketpulse.clients.alphavantage import AlphaVantageClient
    from marketpulse.clients.frankfurter import FrankfurterClient

    async with httpx.AsyncClient() as http:
        assert isinstance(
            await build_client("alphavantage", http, db_session, settings),
            AlphaVantageClient,
        )
        assert isinstance(
            await build_client("frankfurter", http, db_session, settings),
            FrankfurterClient,
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_ingest_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marketpulse.ingest.jobs'`

- [ ] **Step 3: Write `ingest/jobs.py`**

```python
from datetime import date, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from marketpulse.clients.alphavantage import AlphaVantageClient
from marketpulse.clients.coingecko import CoinGeckoClient
from marketpulse.clients.finnhub import FinnhubClient
from marketpulse.clients.frankfurter import FrankfurterClient
from marketpulse.clients.fred import FredClient
from marketpulse.config import Settings
from marketpulse.core.ratelimit import RATE_LIMITS, TokenBucket
from marketpulse.ingest.crypto import ingest_crypto_history, ingest_crypto_snapshot
from marketpulse.ingest.fx import ingest_fx
from marketpulse.ingest.macro import ingest_macro
from marketpulse.ingest.news import ingest_earnings, ingest_news, ingest_ratings
from marketpulse.ingest.prices import ingest_prices
from marketpulse.ingest.runner import calls_used_today, run_job
from marketpulse.universe import CRYPTO_LIMIT, EQUITIES, FRED_SERIES, FX_START

JOB_NAMES: tuple[str, ...] = (
    "prices", "macro", "crypto", "news", "earnings", "ratings", "fx",
)

_JOB_SOURCE: dict[str, str] = {
    "prices": "alphavantage",
    "macro": "fred",
    "crypto": "coingecko",
    "news": "finnhub",
    "earnings": "finnhub",
    "ratings": "finnhub",
    "fx": "frankfurter",
}


def job_source(job: str) -> str:
    return _JOB_SOURCE[job]


async def build_client(
    source: str, http: httpx.AsyncClient, session: AsyncSession, settings: Settings
):
    limiter = TokenBucket(RATE_LIMITS[source])
    if RATE_LIMITS[source].daily_cap is not None:
        limiter.set_daily_used(await calls_used_today(session, source))

    if source == "alphavantage":
        return AlphaVantageClient(http, settings.alphavantage_api_key, limiter)
    if source == "fred":
        return FredClient(http, settings.fred_api_key, limiter)
    if source == "finnhub":
        return FinnhubClient(http, settings.finnhub_api_key, limiter)
    if source == "coingecko":
        return CoinGeckoClient(http, limiter)
    if source == "frankfurter":
        return FrankfurterClient(http, limiter)
    raise KeyError(f"unknown source {source}")


async def run_source(job: str, *, full: bool, session_factory, settings: Settings) -> int:
    source = job_source(job)
    today = date.today()

    async def _run(session: AsyncSession):
        async with httpx.AsyncClient() as http:
            client = await build_client(source, http, session, settings)

            if job == "prices":
                return await ingest_prices(session, client, EQUITIES, full=full)
            if job == "macro":
                return await ingest_macro(session, client, FRED_SERIES)
            if job == "crypto":
                if full:
                    coins = [c.coin_id for c in
                             await client.fetch_top_markets(limit=CRYPTO_LIMIT)]
                    return await ingest_crypto_history(session, client, coins)
                return await ingest_crypto_snapshot(session, client, CRYPTO_LIMIT)
            if job == "news":
                window = 365 if full else 7
                return await ingest_news(session, client, EQUITIES,
                                         today - timedelta(days=window), today)
            if job == "earnings":
                return await ingest_earnings(session, client,
                                             today - timedelta(days=90),
                                             today + timedelta(days=90))
            if job == "ratings":
                return await ingest_ratings(session, client, EQUITIES)
            if job == "fx":
                return await ingest_fx(session, client, FX_START)
            raise KeyError(f"unknown job {job}")

    return await run_job(session_factory, source, job, _run)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_ingest_jobs.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Write `ingest/__main__.py`**

The spec calls for `python -m marketpulse.ingest backfill --source <name>`, so the CLI lives in the package's `__main__`.

```python
import asyncio

import typer

from marketpulse.config import get_settings
from marketpulse.db.session import make_engine, make_session_factory
from marketpulse.ingest.jobs import JOB_NAMES, run_source

app = typer.Typer(help="Market Pulse ingest jobs.")


async def _execute(jobs: tuple[str, ...], full: bool) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    try:
        for job in jobs:
            typer.echo(f"running {job} (full={full}) ...")
            run_id = await run_source(job, full=full, session_factory=session_factory,
                                      settings=settings)
            typer.echo(f"  ingest_run id={run_id}")
    finally:
        await engine.dispose()


@app.command()
def backfill(
    source: str = typer.Option(..., help="Job name, or 'all' for every job."),
) -> None:
    """Load full history. Run once per source."""
    jobs = JOB_NAMES if source == "all" else (source,)
    for job in jobs:
        if job not in JOB_NAMES:
            raise typer.BadParameter(f"unknown job {job}; choose from {JOB_NAMES} or 'all'")
    asyncio.run(_execute(tuple(jobs), full=True))


@app.command()
def daily(
    source: str = typer.Option(..., help="Job name, or 'all' for every job."),
) -> None:
    """Incremental refresh. What the Cloudflare cron triggers call."""
    jobs = JOB_NAMES if source == "all" else (source,)
    for job in jobs:
        if job not in JOB_NAMES:
            raise typer.BadParameter(f"unknown job {job}; choose from {JOB_NAMES} or 'all'")
    asyncio.run(_execute(tuple(jobs), full=False))


if __name__ == "__main__":
    app()
```

- [ ] **Step 6: Verify the CLI wiring without spending API quota**

```bash
cd apps/api
uv run python -m marketpulse.ingest --help
uv run python -m marketpulse.ingest backfill --source nonsense
```

Expected: the first prints `backfill` and `daily` commands; the second exits non-zero with `unknown job nonsense`.

- [ ] **Step 7: Run the full suite**

Run: `cd apps/api && uv run pytest -v`
Expected: PASS, all tests across all files.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/marketpulse/ingest/jobs.py apps/api/src/marketpulse/ingest/__main__.py apps/api/tests/test_ingest_jobs.py
git commit -m "feat: add job registry and backfill CLI"
```

- [ ] **Step 9: Run the real backfill against a live database**

This is the one step that spends real API quota. Do it once, in this order, and check `ingest_run` after each.

```bash
cd apps/api
export DATABASE_URL=<neon-or-local-url>
export ALPHAVANTAGE_API_KEY=... FRED_API_KEY=... FINNHUB_API_KEY=... INGEST_HMAC_SECRET=...
uv run alembic upgrade head

uv run python -m marketpulse.ingest backfill --source fx        # 1 call
uv run python -m marketpulse.ingest backfill --source macro     # 30 calls
uv run python -m marketpulse.ingest backfill --source crypto    # 21 calls
uv run python -m marketpulse.ingest backfill --source prices    # 15 calls, spends most of the daily 25
uv run python -m marketpulse.ingest backfill --source news      # 15 calls
uv run python -m marketpulse.ingest backfill --source earnings  # 1 call
uv run python -m marketpulse.ingest backfill --source ratings   # 15 calls
```

Verify:

```sql
SELECT source, job, status, rows_upserted, api_calls_used, error
FROM ingest_run ORDER BY started_at;
```

Expected: seven rows, all `success`. Any `partial` row names the failing item in `error` — rerun that single job after fixing it, since every job is idempotent.

---

## Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| §3.1 repo layout | Task 1 |
| §3.2 backend module layout | Tasks 1–12 |
| §3.3 module boundaries | Enforced by the fake-client tests in Tasks 7–11 |
| §4.1 series + observation | Task 2 (schema), Task 6 (upserts) |
| §4.2 equities | Task 2, Task 10 |
| §4.3 Finnhub event tables | Task 2, Task 11 |
| §4.4 ingest_run | Task 2, Task 6 |
| §4.5 universe | Task 1 |
| §4.6 idempotency | Asserted in Tasks 6, 7, 8, 9, 10, 11 |
| §5.1 call budget | Task 12 Step 9 |
| §5.2 schedule | Deferred to the deployment plan (cron triggers are Cloudflare config) |
| §5.3 execution flow | `/internal/ingest` route deferred to the API plan; the CLI in Task 12 covers manual invocation |
| §5.4 rate limiting + daily cap | Task 3, wired in Task 12 |
| §5.5 retries | Task 4 |
| §6 failure handling | Task 6 (status rules), Tasks 8–11 (per-item try/except) |
| §7 API surface | Deferred to the API plan |
| §8 testing | Every task |
| §9 frontend | Deferred to the frontend plan |
| §10 deployment | Deferred to the deployment plan |

Three spec sections are deliberately out of this plan's scope: §5.2 (cron config), §5.3's HTTP trigger and §7 (read routes) belong to plan 2, and §9–§10 to plans 2 and 3. §5.1's budget is validated here because the backfill runs here.

**Placeholder scan:** none found. Every code step contains runnable code; every test step contains real assertions.

**Type consistency:** `JobResult` fields (`rows_upserted`, `api_calls_used`, `errors`) are identical across Tasks 6–12. `calls_made` is a property on `BaseClient` and an attribute on every fake, matching. `upsert_series` keyword arguments match between Task 6's definition and its callers in Tasks 7, 8, 9. `client.fetch_daily(symbol, full=...)` matches between Task 10's client and its ingest caller.
