# Jay Trader — Design Spec

**Date:** 2026-09-05
**Status:** Approved
**Type:** Portfolio project — multi-source financial data aggregation service

## 1. Purpose

A polished, demo-sized dashboard that ingests five free financial APIs into one Postgres
database and serves them through a Python REST API to a React frontend hosted on
Cloudflare Pages.

Goal is the build itself: a clean ingest pipeline, a defensible data model, and a
frontend worth screenshotting. Correctness matters more than completeness. Scope stays
deliberately small — no authentication, no user accounts, no multi-tenancy, no alerting.

### Non-goals

- User accounts, authentication, or per-user state
- Redistribution of vendor data (Alpha Vantage free tier forbids it; the app is a
  personal demo, not a public data service)
- Backtest-grade price accuracy (see split-adjustment caveat in §4.5)
- Intraday or real-time data
- Horizontal scaling beyond one API instance

## 2. Data sources

| Source | Provides | Auth | Limit |
|---|---|---|---|
| Alpha Vantage | Daily OHLCV for equities and index ETFs | API key | 25 req/day, 5 req/min |
| FRED (St. Louis Fed) | Macro series: rates, CPI, unemployment, GDP | API key | 120 req/min |
| CoinGecko | Crypto price, market cap, 24h volume | None (public endpoints) | ~30 req/min |
| Finnhub | Company news, earnings calendar, analyst ratings | API key | 60 req/min |
| Frankfurter | ECB daily FX reference rates | None | Unmetered |

Alpha Vantage's 25 requests/day is the binding constraint on the entire system and
drives the symbol universe size, the backfill strategy, and the ingest schedule.

## 3. Architecture

```
                    Cloudflare
  +------------------------------------------+
  |  Pages: React SPA (static, dist/)        |
  |  Cron Trigger Worker (TypeScript)        |
  +-------+---------------------+------------+
          | GET /v1/*           | POST /internal/ingest/{source}
          | (CORS)              | + HMAC-SHA256 signature
          v                     v
  +------------------------------------------+
  |  Fly.io: FastAPI (Python 3.12)           |
  |   read routes  |  ingest routes          |
  |   clients/ (5 API adapters)              |
  |   core/ratelimit (async token bucket)    |
  +-------------------+----------------------+
                      | SQLAlchemy 2.0 async / asyncpg
                      v
              Neon Postgres (scale-to-zero)
```

**Runtime versions.** Python 3.12 in the container (not the 3.14 installed locally) —
asyncpg and pydantic wheel coverage is more reliable on 3.12. Local development matches
the container version via `uv`. Node 24 for the frontend and Worker.

**Why Python does not run on Cloudflare.** Cloudflare Workers execute JavaScript and
WASM. Python Workers exist but are beta with a restricted package set and no arbitrary
pip installs, which rules out asyncpg, SQLAlchemy, and httpx. Cloudflare therefore hosts
the static frontend and the cron scheduler; the Python service runs on Fly.io.

### 3.1 Repository layout

```
market-pulse/
|-- apps/
|   |-- api/          # FastAPI backend (Python)
|   |-- web/          # React + Vite SPA (TypeScript)
|   +-- cron/         # Cloudflare Worker (TypeScript)
|-- docs/
|-- docker-compose.yml   # local Postgres for development
+-- README.md
```

### 3.2 Backend module layout

```
apps/api/src/marketpulse/
|-- main.py              # app factory, CORS, lifespan
|-- config.py            # pydantic-settings; all secrets from env
|-- db/
|   |-- session.py       # async engine + session dependency
|   |-- models.py        # SQLAlchemy 2.0 declarative models
|   +-- migrations/      # alembic
|-- clients/             # HTTP -> typed raw records
|   |-- base.py          # httpx.AsyncClient + tenacity + rate limiter
|   |-- alphavantage.py
|   |-- fred.py
|   |-- coingecko.py
|   |-- finnhub.py
|   +-- frankfurter.py
|-- ingest/              # raw records -> upserted rows
|   |-- runner.py        # wraps every job in an ingest_run record
|   |-- prices.py
|   |-- macro.py
|   |-- crypto.py
|   |-- news.py
|   +-- fx.py
|-- api/
|   |-- routes/          # DB -> JSON
|   |   |-- prices.py  macro.py  crypto.py  news.py  fx.py
|   |   +-- dashboard.py  status.py  health.py
|   +-- deps.py
+-- core/
    |-- ratelimit.py     # async token bucket, per source
    +-- security.py      # HMAC signature verification
```

### 3.3 Module boundaries

The boundary that carries the design: **clients never touch the database, ingest jobs
never make HTTP calls.**

- **`clients/`** — Each client owns one vendor API. It knows base URLs, query parameter
  shapes, auth, pagination, and that vendor's response quirks. It returns plain
  dataclasses. It has no knowledge of SQLAlchemy models or the database.
- **`ingest/`** — Each job takes a client instance by dependency injection, maps
  dataclasses to ORM rows, and upserts them. It makes no HTTP calls of its own.
- **`api/routes/`** — Reads Postgres, serializes to JSON. Never calls a vendor API.

This split is what makes the test strategy in §8 possible: clients test against recorded
JSON fixtures with no database, ingest jobs test against a fake client with no network.

## 4. Data model

Hybrid design. OHLCV is five correlated values per date and earns a dedicated table.
Everything else in the system is one scalar per (thing, date), so FRED observations,
crypto metrics, and FX rates collapse into a single narrow `observation` table behind a
`series` registry. Three sources then share one ingest path, one query path, and one
chart endpoint.

### 4.1 Series registry and observations

```sql
CREATE TABLE series (
  id           bigserial PRIMARY KEY,
  source       text NOT NULL,   -- 'fred' | 'coingecko' | 'frankfurter'
  external_id  text NOT NULL,   -- 'CPIAUCSL' | 'bitcoin:market_cap' | 'EUR/USD'
  name         text NOT NULL,
  unit         text,            -- 'Percent' | 'USD' | 'Index 1982-84=100'
  frequency    text,            -- 'D' | 'W' | 'M' | 'Q'
  category     text NOT NULL,   -- 'rates'|'inflation'|'labor'|'growth'|'crypto'|'fx'
  UNIQUE (source, external_id)
);

CREATE TABLE observation (
  series_id  bigint NOT NULL REFERENCES series(id),
  obs_date   date   NOT NULL,
  value      numeric,
  PRIMARY KEY (series_id, obs_date)
);
CREATE INDEX observation_date_brin ON observation USING brin (obs_date);
```

`value` is nullable: FRED encodes missing observations as `"."`, which maps to NULL
rather than being dropped, so gaps stay visible in charts.

Expected volume: ~500,000 rows.

### 4.2 Equities

```sql
CREATE TABLE asset (
  id       bigserial PRIMARY KEY,
  symbol   text NOT NULL UNIQUE,
  name     text NOT NULL,
  exchange text,
  sector   text
);

CREATE TABLE price_daily (
  asset_id   bigint NOT NULL REFERENCES asset(id),
  trade_date date   NOT NULL,
  open       numeric NOT NULL,
  high       numeric NOT NULL,
  low        numeric NOT NULL,
  close      numeric NOT NULL,
  volume     bigint,
  PRIMARY KEY (asset_id, trade_date)
);
```

Expected volume: 15 symbols x ~6,300 trading days = ~95,000 rows.

### 4.3 Finnhub event tables

These are events, not time series, and are not forced into `observation`.

```sql
CREATE TABLE news (
  id           bigserial PRIMARY KEY,
  symbol       text NOT NULL,
  published_at timestamptz NOT NULL,
  headline     text NOT NULL,
  source       text,
  url          text NOT NULL UNIQUE,
  summary      text,
  image_url    text
);
CREATE INDEX news_symbol_time ON news (symbol, published_at DESC);

CREATE TABLE earnings_calendar (
  symbol            text NOT NULL,
  report_date       date NOT NULL,
  hour              text,          -- 'bmo' | 'amc' | 'dmh'
  eps_estimate      numeric,
  eps_actual        numeric,
  revenue_estimate  bigint,
  revenue_actual    bigint,
  PRIMARY KEY (symbol, report_date)
);

CREATE TABLE analyst_rating (
  symbol      text NOT NULL,
  period      date NOT NULL,
  strong_buy  int,
  buy         int,
  hold        int,
  sell        int,
  strong_sell int,
  PRIMARY KEY (symbol, period)
);
```

`news.url` carries the UNIQUE constraint because Finnhub returns overlapping windows
across polls; the URL is the natural deduplication key.

### 4.4 Pipeline observability

```sql
CREATE TABLE ingest_run (
  id             bigserial PRIMARY KEY,
  source         text NOT NULL,
  job            text NOT NULL,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz,
  status         text NOT NULL,  -- 'running'|'success'|'partial'|'failed'
  rows_upserted  int NOT NULL DEFAULT 0,
  api_calls_used int NOT NULL DEFAULT 0,
  error          text
);
CREATE INDEX ingest_run_source_time ON ingest_run (source, started_at DESC);
```

This table serves two purposes: it enforces the Alpha Vantage daily cap (§5.4), and it
backs the Pipeline view in the frontend.

### 4.5 Universe and known caveat

- **Equities (15):** SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA,
  JPM, XOM, JNJ, WMT
- **FRED (15):** DFF, DGS10, DGS2, T10Y2Y, CPIAUCSL, PCEPI, UNRATE, PAYEMS, GDPC1,
  M2SL, VIXCLS, MORTGAGE30US, INDPRO, HOUST, UMCSENT
- **Crypto:** top 20 by market cap from `/coins/markets`
- **FX:** EUR base against Frankfurter's full quote set (~30 currencies)

**Split-adjustment caveat.** `TIME_SERIES_DAILY_ADJUSTED` is an Alpha Vantage premium
endpoint. The free `TIME_SERIES_DAILY` returns raw OHLCV only, so stock splits appear as
price discontinuities. **Decision: store raw prices and label the affected charts in the
UI as unadjusted.** The dashboard is macro-oriented rather than backtest-grade, and a
hand-maintained split table would be quiet technical debt.

### 4.6 Idempotency

Every write is `INSERT ... ON CONFLICT DO UPDATE`. Any ingest job can be rerun for any
date range without duplicating or corrupting rows. This is what makes backfill, replay,
and partial-failure recovery safe, and it is asserted directly in the test suite (§8).

## 5. Ingest

### 5.1 API call budget

| Source | Limit | Backfill | Daily steady state |
|---|---|---|---|
| Alpha Vantage | 25/day, 5/min | 15 (`outputsize=full`, 20+ yrs in one call each) | 15 (`outputsize=compact`) |
| FRED | 120/min | 15 | 15 |
| CoinGecko | ~30/min | 20 (`market_chart?days=max`) | 1 (`/coins/markets` covers all 20) |
| Finnhub | 60/min | 15 | ~17 (news + calendar + ratings) |
| Frankfurter | none | 1 (`/v1/1999-01-04..?base=EUR`) | 1 |

Alpha Vantage backfill fits inside a single day's 25-request budget with 10 calls of
headroom. `outputsize=full` returning 20+ years in one call is the reason this project is
viable on the free tier at all.

### 5.2 Schedule

Cloudflare Cron Triggers, all times UTC:

```
15 13 * * *    fred        # after 08:30 ET data releases
30 15 * * 1-5  fx          # after ECB ~15:00 UTC publish
0  22 * * 1-5  prices      # after US close 21:00 UTC
0  */6 * * *   crypto      # snapshot 4x daily
0  */6 * * *   news
0  23 * * *    earnings
0  4  * * 1    ratings     # weekly
```

Backfill is not scheduled. It is a one-time manual CLI invocation:

```
python -m marketpulse.ingest backfill --source alphavantage
```

### 5.3 Execution flow

The Cloudflare Worker fires on schedule and issues a signed POST to
`/internal/ingest/{source}`. FastAPI verifies the signature, returns `202 Accepted`
immediately, and runs the job as a `BackgroundTask`. The Worker does not wait for job
completion — it only needs to confirm the job was accepted.

Because ingest is plain HTTP, any job can be replayed by hand with `curl` and a
correctly signed header, which is the main operational advantage over an in-process
scheduler.

### 5.4 Rate limiting

One async token bucket per source, shared by every call that source's client makes:

```python
RATE_LIMITS = {
    "alphavantage": Bucket(rate=5,   per=60, daily_cap=25),
    "fred":         Bucket(rate=100, per=60),
    "coingecko":    Bucket(rate=20,  per=60),
    "finnhub":      Bucket(rate=50,  per=60),
    "frankfurter":  Bucket(rate=60,  per=60),
}
```

Buckets live in process memory. This is correct because the service runs as a single
instance; scaling past one instance would require moving the buckets to shared state, and
that is explicitly out of scope.

`daily_cap` is enforced against `SUM(api_calls_used)` over today's `ingest_run` rows for
that source, so a bug in a loop cannot consume the next day's budget. When the cap is
reached the client raises `DailyCapExceeded` and the run is marked `partial`.

### 5.5 Retries

`tenacity` on the client base class: exponential backoff, maximum 3 attempts, retrying
only on HTTP 429, HTTP 5xx, and connection timeouts. A 429 carrying `Retry-After` honors
that header instead of the computed backoff. HTTP 4xx other than 429 fails immediately —
retrying a malformed request or a bad key wastes quota.

## 6. Failure handling

**The governing property: ingest failure never degrades reads.** Read routes touch only
Postgres. They serve last-known-good data regardless of upstream availability. A dead
Alpha Vantage means yesterday's closing prices, not a broken dashboard.

Within a run, each item is wrapped in its own `try/except`:

- One symbol fails, fourteen succeed: run is marked `partial`, the error text is recorded
  on the `ingest_run` row, and the fourteen successful upserts are committed.
- The run throws before any write (bad credentials, DNS failure): marked `failed`, no
  rows written.
- The run completes with no errors: marked `success`.

The `/v1/status` route surfaces the most recent run per source so failures are visible in
the frontend rather than buried in logs.

## 7. API surface

```
GET  /v1/health
GET  /v1/dashboard                     # aggregated payload for first paint
GET  /v1/assets
GET  /v1/prices/{symbol}?from=&to=
GET  /v1/series?category=
GET  /v1/series/{source}/{external_id}/observations?from=&to=
GET  /v1/crypto/top?limit=20
GET  /v1/fx/convert?from=USD&to=JPY&amount=100&date=2024-01-15
GET  /v1/news?symbol=&limit=50
GET  /v1/earnings/upcoming?days=14
GET  /v1/ratings/{symbol}
GET  /v1/status

POST /internal/ingest/{source}         # HMAC-signed, Worker only
```

Read routes send `Cache-Control: public, s-maxage=3600` so Cloudflare's edge absorbs
repeat traffic — data updates at most daily, so an hour of edge cache is free
performance. `/internal/*` sends `Cache-Control: no-store`.

`/v1/dashboard` exists so the Overview page makes one request instead of seven.

### 7.1 Internal endpoint authentication

The Worker computes `HMAC-SHA256(secret, f"{timestamp}.{source}")` and sends it as
`X-Signature` alongside `X-Timestamp`.

The API:

1. Rejects requests whose `X-Timestamp` is more than 300 seconds old (replay window).
2. Recomputes the HMAC and compares with `hmac.compare_digest` (constant-time).
3. Returns `401` on any mismatch, with no detail in the response body.

The shared secret is stored as a Fly.io secret and a Cloudflare Worker secret binding. It
never appears in the repository, in any committed config file, or in the frontend bundle.

## 8. Testing

- **Clients** — `respx` intercepts httpx. Recorded JSON fixtures captured once from each
  real API live in `tests/fixtures/`. No network, no database. Covers response parsing,
  pagination, and each vendor's error shapes.
- **Ingest jobs** — A fake client returns fixture dataclasses; a real Postgres instance
  comes from `docker-compose`. Each job runs twice in a single test and asserts identical
  row counts, proving the idempotency claim in §4.6.
- **Routes** — Seeded database, `httpx.AsyncClient` against the app, asserting status
  codes, response shape, and cache headers.
- **Security** — Explicit tests for expired timestamps, wrong signatures, and missing
  headers against `/internal/*`.
- **Migrations** — CI runs `alembic upgrade head`, `downgrade base`, `upgrade head`.
- **Frontend** — `vitest` with `msw` mocking the API.

## 9. Frontend

React 19 + Vite + TypeScript, built to static assets and deployed to Cloudflare Pages.
React Router for navigation, TanStack Query for fetching and caching (`staleTime: 5min`,
matching the edge cache window). ECharts for charts — time-series brush zoom and shared
crosshairs across linked charts come free, and it renders 6,000 daily points without
degrading.

Views:

1. **Overview** — dashboard tiles with sparklines, drawn from `/v1/dashboard`
2. **Markets** — price charts, multi-symbol comparison
3. **Macro** — FRED series with normalized overlays
4. **Crypto** — market cap treemap and dominance chart
5. **FX** — currency converter and rate history
6. **News & Earnings** — news feed and upcoming earnings calendar
7. **Pipeline** — `ingest_run` history table

`VITE_API_BASE` is configured per Pages environment (preview and production).

## 10. Deployment

| Component | Platform | Artifact |
|---|---|---|
| API | Fly.io | `Dockerfile` + `fly.toml`, 1 instance, 256MB |
| Database | Neon | Free tier, scale-to-zero, connection pooler endpoint |
| Frontend | Cloudflare Pages | `npm run build` -> `apps/web/dist` |
| Cron | Cloudflare Workers | `wrangler.toml` with cron triggers |

Secrets: `ALPHAVANTAGE_API_KEY`, `FRED_API_KEY`, `FINNHUB_API_KEY`, `DATABASE_URL`,
`INGEST_HMAC_SECRET` as Fly secrets. `INGEST_HMAC_SECRET` and `API_BASE_URL` as Worker
secrets. `.env.example` is committed with every key name present and every value blank.

Neon's scale-to-zero introduces a cold-start delay of a few seconds on the first query
after idle. This is acceptable for a portfolio demo and is not worked around.

## 11. Build order

1. Repo scaffold, `docker-compose` Postgres, `config.py`, alembic baseline
2. `clients/base.py` + rate limiter + Frankfurter client end to end
3. Remaining four clients and their ingest jobs
4. Backfill CLI, executed once against Neon
5. Read routes and OpenAPI schema
6. React frontend
7. Dockerfile to Fly, Pages deploy, Worker cron, secrets wiring

Frankfurter is deliberately first: it exercises the full pipeline — client, ingest,
`series`/`observation` tables, read route, chart — with no API key to obtain and no rate
limit to design around. Every later source then slots into a proven path.
