# Known follow-ups

Non-blocking items found during review of the backend ingest pipeline. None of these
block merge; all were surfaced by review and consciously deferred.

## Before running against live vendor APIs

- **Clamp `Retry-After`.** `clients/base.py`'s `wait_retry_after_or_backoff` honors the
  header verbatim with no ceiling, and applies it on every retry. A vendor answering
  `Retry-After: 3600` blocks a job for ~2 hours, where the previous ceiling was 8s. Spec
  §5.5 names no cap so the current behavior is spec-faithful, but `min(header, 60)` is
  cheap insurance.

- **Only `ingest_prices` breaks on a vendor throttle.** `news`, `ratings`, `macro`, and
  `crypto` still catch `RateLimited` under their generic handler and keep going, each
  remaining item blocking in the token bucket. Harmless but slow; worth propagating the
  `break` if any of those universes grows.

- **`ingest_fx` is all-or-nothing.** It has no per-pair `try` and no savepoint, so one bad
  currency pair fails the whole job. Defensible for a single-call job — it is the only one
  of seven without per-item isolation.

## Vendor unknowns that fixtures cannot verify

Recorded from the final review. These are not code defects — they are the gap between a
recorded fixture and a live vendor, and are the things to watch on the first real backfill.

- **Alpha Vantage response-shape drift.** Throttle detection keys on the literal strings
  `"Note"` and `"Information"`. Alpha Vantage has changed that wording before.
- **Alpha Vantage's real reset clock.** `calls_used_today` buckets on UTC midnight. If the
  vendor resets on a different clock, the seeded count is off near the boundary.
- **CoinGecko's real anonymous rate limit.** The bucket assumes 20/min; the public API is
  known to enforce something stricter and more variable, especially from cloud IPs.
- **FRED series IDs.** All 15 are hardcoded and have never touched the live API. A
  discontinued ID degrades to a `partial` run rather than a crash.
- **Finnhub free-tier gating.** The 365-day news backfill window is a common place for free
  plans to truncate or reject outright.

## Data model consequences worth knowing before the read API

- **`news.url` is UNIQUE, so a story tagged for two symbols is attributed to whichever job
  ran first.** `ingest_news` dedupes per symbol and the cross-symbol `ON CONFLICT` updates
  headline/summary/published_at but not `symbol`. A story about both AAPL and MSFT will not
  appear under MSFT. This follows from the spec's own choice of `url` as the dedup key.

- **Prices are raw and unadjusted.** `TIME_SERIES_DAILY_ADJUSTED` is an Alpha Vantage
  premium endpoint, so splits appear as price discontinuities. Documented tradeoff from
  spec §4.5 — label affected charts in the UI.

- **Daily FX and macro jobs rewrite full history every run.** `ingest_fx` always passes
  `FX_START` (1999-01-04) and `ingest_macro` ignores its `start` parameter, so each daily
  run re-upserts ~200k observation rows. Idempotent and correct, just expensive against a
  scale-to-zero database — and it makes `rows_upserted` report rows *touched* rather than
  rows *changed*, so the Pipeline view reads ~200k daily forever.

- **FRED costs 2x its budgeted calls.** `ingest_macro` fetches series metadata and
  observations separately: 30 calls against the 15 budgeted in spec §5.1. Well under FRED's
  120/min limit, but the metadata rarely changes and need not be refetched daily.

## Test coverage gaps

- **`test_a_database_failure_on_one_news_symbol_keeps_the_others` puts the failing symbol
  last**, so it never proves the session stays usable for a *later* symbol. The property
  was verified manually with a mid-list failure; the test just does not encode it.

- **Nine `PytestWarning`s** from sync tests inheriting a module-level `pytest.mark.asyncio`.
  Cosmetic; the tests execute correctly.

## Rate limiter

- **One `TokenBucket` per job, not per source.** `build_client` constructs a fresh bucket
  per `run_job`, so Finnhub's three jobs each start with a full 50-token bucket — up to 150
  tokens/minute against a 60/min vendor limit. Spec §5.4 specifies one bucket per source.
  Safe at current volume (31 calls total) and no daily-cap source is affected, but it stops
  being safe if the universe grows.

## Read API — live verification (Task 10, 2026-09-06/07)

Ran the API (`uv run uvicorn marketpulse.main:app --port 8000`) against the live Neon
database with only the `fx` source backfilled (~46 series, ~265,615 observations,
1999-01-04 to 2026-09-04; `asset`, `price_daily`, FRED/crypto series, `news`,
`earnings_calendar`, and `analyst_rating` all empty). Full request/response log is in
`.superpowers/sdd/2026-09-06-read-api/task-10-report.md`.

- **No 500s anywhere.** Every route with no ingested data (`/v1/assets`,
  `/v1/crypto/top`, `/v1/news`, `/v1/earnings/upcoming`, `/v1/ratings/{symbol}`) returned
  200 with `[]`. `/v1/dashboard` returned 200 with empty `markets`/`macro`/`crypto`/
  `upcoming_earnings` and a populated `pipeline` (the one real `fx` ingest run).
  `/v1/prices/AAPL` correctly 404s (`not_found`, resource `symbol`) since `asset` is
  empty — a single-resource lookup, not a list, so 404 rather than `[]` is correct
  per `errors.py`/`assets.py`.
- **`/v1/fx/convert` cross-rate checks out.** Verified `USD→JPY` by hand against the
  stored EUR-denominated rates: on 2026-09-04, EUR/USD = 1.1622 and EUR/JPY = 181.59,
  and `EUR/JPY ÷ EUR/USD` = 156.247, matching the API's returned rate
  (156.24677336086734) to full precision. Not inverted, not stale.
- **Cache-Control is correctly conditional.** `public, s-maxage=3600` appears on every
  200 GET and is absent on the 404 from `/v1/prices/{symbol}` — by design
  (`CacheControlMiddleware` only sets it for `status_code == 200`), so an error is never
  pinned at Cloudflare's edge for an hour.
- **Dashboard timing — floor only, not full-universe.** `/v1/dashboard` averaged
  **~1.2s** (1.19s, 1.24s, 1.19s across three runs) against the live Neon instance with
  **zero** assets and **zero** FRED series loaded, i.e. the per-asset/per-series query
  loop in Task 8 executed zero times. This is strictly a floor: the brief estimates
  ~35 round trips once assets, FRED series, crypto, and earnings are all backfilled, and
  none of the per-item cost is reflected in this number yet. 1.2s already for `pipeline`
  and the four empty aggregation queries alone is worth watching — if scale-to-zero
  cold-start dominates, adding 30+ more round trips per dashboard load in the full-universe
  case is a realistic path past 2s, and would be worth collapsing into a single windowed
  query per section (e.g. one query for all tracked assets' latest+prior close, one for all
  FRED series' latest observation) rather than one query per row.
- **OpenAPI contract is complete.** All 13 routes (12 `/v1/*` GETs plus
  `POST /internal/ingest/{source}`) appear in `/openapi.json` with typed response models
  (`AssetOut`, `CoinOut`, `DashboardOut`, `EarningsOut`, `FxConversionOut`,
  `IngestRunOut`, `NewsOut`, `ObservationOut`, `PriceBarOut`, `RatingOut`, `SeriesOut`);
  the internal ingest route correctly documents `202` rather than `200`. `/docs` renders.
- **Full suite still green:** 211 passed against the local test Postgres, no regressions
  from the read-side work.
