# Market Pulse

Aggregates five free financial APIs into one Postgres database and serves them
through a FastAPI read API. Frontend and Cloudflare deployment are not built yet.

- Design spec: [`docs/superpowers/specs/2026-09-05-market-pulse-design.md`](docs/superpowers/specs/2026-09-05-market-pulse-design.md)
- API reference: [`apps/api/README.md`](apps/api/README.md)
- Known follow-ups: [`docs/FOLLOWUPS.md`](docs/FOLLOWUPS.md)

| Source | Data | Job name |
|---|---|---|
| Alpha Vantage | Daily OHLCV, 15 equities | `prices` |
| FRED | 15 macro series | `macro` |
| CoinGecko | Top 20 coins: price, market cap, volume | `crypto` |
| Finnhub | Company news / earnings calendar / analyst ratings | `news`, `earnings`, `ratings` |
| Frankfurter | ECB daily FX, EUR base, ~46 pairs | `fx` |

---

## Prerequisites

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Postgres — a local instance on port 5433 for tests, plus a `DATABASE_URL`
  (Neon) for real data
- A `.env` at the repo root (see `.env.example`)

One-time setup:

```bash
cd apps/api
uv sync --extra dev
uv run alembic upgrade head
```

---

## Run the server

```bash
cd apps/api
uv run uvicorn marketpulse.main:app --reload --port 8000
```

- API: <http://127.0.0.1:8000>
- Swagger UI: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/v1/health>

Drop `--reload` when you want it quiet; add `--log-level warning` to suppress
access logs.

---

## Backfill data

`--source` takes a **job name** from the table above, or `all`. It does *not*
take a vendor name — `--source fred` is rejected, `--source macro` is correct.

Run these from `apps/api`. Backfill loads full history and is meant to run once
per source.

```bash
# Free and generous. Decades of CPI, unemployment, yields. Start here.
uv run python -m marketpulse.ingest backfill --source macro

# Top 20 coins, full daily history. ~21 calls.
uv run python -m marketpulse.ingest backfill --source crypto

# Finnhub. 365-day news window, ±90-day earnings calendar, current ratings.
uv run python -m marketpulse.ingest backfill --source news
uv run python -m marketpulse.ingest backfill --source earnings
uv run python -m marketpulse.ingest backfill --source ratings

# ECB FX since 1999. One call, ~265k rows.
uv run python -m marketpulse.ingest backfill --source fx

# Alpha Vantage. Spends 15 of the 25 daily requests — one attempt per day.
uv run python -m marketpulse.ingest backfill --source prices

# Everything at once. Only safe if the Alpha Vantage budget is untouched today.
uv run python -m marketpulse.ingest backfill --source all
```

### Daily refresh

What the Cloudflare cron triggers will call once deployed. Incremental, not full
history.

```bash
uv run python -m marketpulse.ingest daily --source all
uv run python -m marketpulse.ingest daily --source prices
```

### Check what ran

Every job writes an `ingest_run` row. Read them back without opening psql:

```bash
curl -s http://127.0.0.1:8000/v1/status
```

Status is `success`, `partial` (some items failed, the rest committed), or
`failed` (nothing written). The CLI also prints a summary line and exits `1` if
any job failed.

---

## API call budget

Alpha Vantage's 25 requests/day is the binding constraint on the whole project.

| Source | Limit | Backfill cost | Daily cost |
|---|---|---|---|
| Alpha Vantage | 25/day, 5/min | 15 | 15 |
| FRED | 120/min | 15 | 15 |
| CoinGecko | ~30/min | 21 | 1 |
| Finnhub | 60/min | ~17 | ~17 |
| Frankfurter | none | 1 | 1 |

The daily cap is enforced against today's `ingest_run` rows, so a bug cannot
spend tomorrow's budget.

---

## Tests

```bash
cd apps/api
uv run pytest -q
```

233 tests, roughly 8 seconds, no network access. Requires the local Postgres on
port 5433. Override with `TEST_DATABASE_URL` if yours differs:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5433/marketpulse_test \
  uv run pytest -v
```

---

## Repository layout

```
market-pulse/
├── apps/
│   └── api/                      # FastAPI backend
│       ├── src/marketpulse/
│       │   ├── clients/          # HTTP -> typed records. Never touches the DB.
│       │   ├── ingest/           # records -> upserts. Never makes HTTP calls.
│       │   ├── api/routes/       # DB -> JSON. Never calls a vendor.
│       │   ├── core/             # rate limiting, HMAC verification
│       │   └── db/               # models, session, migrations
│       └── tests/
└── docs/
    ├── FOLLOWUPS.md
    └── superpowers/{specs,plans}/
```

Not built yet: `apps/web` (React SPA) and `apps/cron` (Cloudflare Worker).
