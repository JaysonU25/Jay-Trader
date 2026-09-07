# Market Pulse API

FastAPI service over the ingested financial data. Reads only; ingest runs
through the CLI or the signed internal endpoint.

## Setup

Requires Python 3.12 and `uv`. Configuration comes from `.env` at the repo root:

```
DATABASE_URL=postgresql://...        # any Postgres URL; normalised automatically
ALPHAVANTAGE_API_KEY=
FRED_API_KEY=
FINNHUB_API_KEY=
INGEST_HMAC_SECRET=                  # python -c "import secrets; print(secrets.token_urlsafe(32))"
CORS_ORIGINS=                        # comma-separated frontend origins
```

`Settings` resolves `.env` by walking up from this package to the repo root
(`apps/api/.env` first, then `<repo root>/.env`), so it is found the same way
regardless of the directory you run commands from.

Provider connection strings are accepted as printed and normalised at load time:

- `postgresql://` (and `postgres://`) is rewritten to `postgresql+asyncpg://`
  so the async driver is always used, no matter what the provider's dashboard
  prints.
- `sslmode=` (a libpq-only parameter asyncpg rejects) is rewritten to `ssl=`.
- Libpq-only query parameters such as `channel_binding` are stripped outright,
  since asyncpg has no equivalent and errors on unknown parameters.
- At engine creation, `make_engine` detects a pooled endpoint — Neon's
  `-pooler` host or Supabase's port `6543` — and disables asyncpg's statement
  cache for it. Both are PgBouncer in transaction-pooling mode, which does not
  keep a prepared statement alive across the pooled connection's lifetime;
  without disabling the cache, asyncpg's second use of a cached statement
  fails with `prepared statement "__asyncpg_stmt_1__" does not exist`.

```bash
cd apps/api
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn marketpulse.main:app --reload
```

Interactive docs at `/docs`.

## Routes

| Route | Purpose |
|---|---|
| `GET /v1/health` | Liveness |
| `GET /v1/dashboard` | Aggregated Overview payload |
| `GET /v1/assets` | Tracked equities |
| `GET /v1/prices/{symbol}?from=&to=` | Daily OHLCV |
| `GET /v1/series?category=` | Series catalogue |
| `GET /v1/series/{source}/{external_id}/observations` | Time series |
| `GET /v1/crypto/top?limit=` | Coins by market cap |
| `GET /v1/fx/convert?from=&to=&amount=&date=` | Currency conversion |
| `GET /v1/news?symbol=&limit=` | Company news |
| `GET /v1/earnings/upcoming?days=` | Earnings calendar |
| `GET /v1/ratings/{symbol}` | Analyst ratings |
| `GET /v1/status` | Latest ingest run per source |
| `POST /internal/ingest/{source}` | Trigger a job (HMAC-signed) |

Read routes send `Cache-Control: public, s-maxage=3600`; `/internal/*` sends
`no-store`. The header is only applied to successful (200) GETs, so a 404 from
`/v1/prices/{symbol}` or similar is never pinned at the edge.

## Ingest

```bash
uv run python -m marketpulse.ingest backfill --source fx
uv run python -m marketpulse.ingest daily --source all
```

Alpha Vantage's free tier allows 25 requests/day and `prices` spends 15, so it
gets one attempt per day.

## Tests

```bash
TEST_DATABASE_URL=postgresql+asyncpg://marketpulse:marketpulse@localhost:5433/marketpulse_test \
  uv run pytest -v
```

Requires a local Postgres; no test touches the network.

## Verified against live data

Every route above was walked against the live Neon database with the `fx`
source backfilled (~46 FX series, ~265k observations, 1999-01-04 through
2026-09-04) and every other source empty. Full results are recorded in
`.superpowers/sdd/2026-09-06-read-api/task-10-report.md`. Summary: all routes
returned 200 with either real data or an empty list/section, matching the
data actually present — no 500s. `/v1/dashboard` took roughly 1.2s cold
against Neon with zero assets and zero FRED series loaded, which is a floor,
not the full-universe cost (see `docs/FOLLOWUPS.md`).
