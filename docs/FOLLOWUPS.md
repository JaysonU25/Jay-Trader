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

Recorded from the final review. Several have since been settled against the live vendors;
those are marked RESOLVED with what actually happened, because in two cases the guess was
wrong in a way worth remembering.

- **RESOLVED — Alpha Vantage response-shape drift.** Predicted correctly, and it bit. The
  free tier now refuses `outputsize=full` as a premium feature, and delivers that refusal
  under the same `"Information"` key a throttle uses. Because the client classified any
  `"Information"` body as a throttle, `ingest_prices` broke out of its loop on the first
  symbol and all fifteen died after one request. The client now distinguishes an
  entitlement refusal (permanent) from a throttle (clears on its own), and the prices job
  always requests `outputsize=compact`.
- **RESOLVED — CoinGecko's real anonymous rate limit.** The prediction was wrong about the
  mechanism. The crypto backfill did fail on every coin, but not from throttling and not
  from the missing key: `days=max` is refused with **HTTP 401 and `error_code` 10012**,
  "Public API users are limited to querying historical data within the past 365 days."
  A 401 that means "range too long" reads exactly like an auth failure, and cost a
  detour through API-key plumbing before the real cause surfaced. Anonymous requests at
  `days=365` succeed. A demo key raises the rate limit but does **not** lift the range cap.
- **Alpha Vantage's real reset clock.** `calls_used_today` buckets on UTC midnight. If the
  vendor resets on a different clock, the seeded count is off near the boundary.
- **Alpha Vantage's per-minute pacing is tighter than the bucket assumes.** The first
  successful prices backfill got 12 of 15 symbols before a genuine throttle
  ("please consider spreading out your free API requests") stopped the loop. The 5/min
  bucket permits an opening burst the vendor does not actually welcome.
- **FRED series IDs.** All 15 are hardcoded. Confirmed working against the live API:
  the macro backfill landed 89,819 observations across 15 series.
- **Finnhub free-tier gating.** Partly confirmed. News backfilled fine (3,663 rows across
  15 symbols) but the earnings calendar returned only **2 rows** for a ±90-day window,
  which is the free plan truncating.

## Data model consequences worth knowing before the read API

- **`news.url` is UNIQUE, so a story tagged for two symbols is attributed to whichever job
  ran first.** `ingest_news` dedupes per symbol and the cross-symbol `ON CONFLICT` updates
  headline/summary/published_at but not `symbol`. A story about both AAPL and MSFT will not
  appear under MSFT. This follows from the spec's own choice of `url` as the dedup key.

- **Prices are raw and unadjusted.** `TIME_SERIES_DAILY_ADJUSTED` is an Alpha Vantage
  premium endpoint, so splits appear as price discontinuities. Documented tradeoff from
  spec §4.5 — the Markets view carries the label.

- **History depth now varies by source, and the spec's "full history" no longer holds
  across the board.** FX reaches 1999 and FRED reaches each series' start, but equities are
  capped at 100 trading days (`outputsize=compact`) and crypto at 365 days, both by vendor
  paywall rather than by choice. Spec §4.5 and §5.1 assume deeper equity history than the
  free tier will now serve. Deciding whether to pay Alpha Vantage or swap the equity source
  (Tiingo and Stooq both offer longer free history) is an open product question.

- **A long ingest job holds one transaction across every HTTP call.** `run_job` opens one
  session and hands it to the job, which then makes 15-20 vendor requests inside it. When
  the crypto backfill was failing slowly, Neon closed the idle connection mid-job and the
  entire transaction was lost — including its audit row, which surfaced as a confusing
  `InterfaceError` in place of the real per-coin errors. `pool_pre_ping` does not help:
  it validates a connection at checkout, not one already held open. The durable fix is
  committing per item rather than per job. Currently masked by the jobs being fast again.

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

## Read API — final review fix wave (2026-09-07)

Ten tasks were individually reviewed; the final whole-branch review found four blockers
plus several important/minor issues. All were fixed in one consolidated pass (233 tests
passing, up from 211).

**Blockers fixed:**
- `/v1/fx/convert`'s `amount` query param now rejects `nan`/`inf` (`allow_inf_nan=False`,
  422), and the computed `result` is checked with `math.isfinite` post-multiplication so a
  finite-but-huge `amount` (e.g. `1e308`) that overflows to `inf` also 422s instead of
  serializing as `null` into a non-nullable float field. `clients/fred.py`'s `_to_decimal`
  now also rejects non-finite `Decimal`s (`NaN`/`Infinity`) the same way it already
  rejected FRED's `"."` sentinel, so a NaN observation can't reach `SparklineOut.points`.
- The internal-ingest test suite no longer risks building a real engine against the
  production database URL: the success-path test now monkeypatches `_run` itself rather
  than `run_source`, so the background task body never executes in tests. Separate focused
  tests exercise `_run` directly (patching `make_engine`/`run_source`) to prove the engine
  is disposed on both the success and exception paths — the `finally` guarantee is now
  under test.
- `/v1/ratings/{symbol}` now 404s for an untracked symbol (pre-checks `Asset.symbol`,
  matching `/v1/prices/{symbol}`'s semantics) while still returning `200 []` for a tracked
  symbol with no ratings. Every route that can 404 (`prices`, `ratings`, series
  observations, `fx/convert`) now declares a 404 response in its OpenAPI via a shared
  `NOT_FOUND_RESPONSE`; `POST /internal/ingest/{source}` declares 401 via
  `UNAUTHORIZED_RESPONSE`. Both are asserted against `/openapi.json`.
- Removed the three branch-introduced `F401` unused imports (`func` in `crypto.py`, two in
  `test_api_schemas.py`); confirmed clean with `ruff check --select F401 .`.

**Important/minor fixed:**
- `IngestRunOut.error` is now sanitized at the read boundary (a `field_validator`, first
  line only, capped at 200 chars) so a raw exception message — potentially containing SQL
  text, bound parameters, or a vendor API key embedded in a URL — can never sit behind
  `/v1/status`'s or `/v1/dashboard`'s hour-long edge cache. The stored value is untouched.
- `core/security.py`'s replay window was accepting timestamps up to 300s in the *future* on
  top of 300s in the past (an effective ~600s window against spec §7.1's 300s). Now the
  past bound stays at `max_age_seconds` and the future side gets a fixed 30s clock-skew
  allowance only.
- `/v1/fx/convert`'s rate lookup now filters on `Series.source == "frankfurter"` in addition
  to `external_id`, so a second source writing the same `external_id` can't trigger
  `MultipleResultsFound` (500). The observation query also excludes `value == 0`, closing
  an uncaught `ZeroDivisionError` path.
- `POST /internal/ingest/{source}`'s unknown-job 404 now uses the shared `not_found()` body
  instead of a bare string, matching every other 404 in the API (this path is past
  signature verification, so it isn't part of the deliberately-opaque 401 surface).
- `/v1/series` and `/v1/series/{source}/{external_id}/observations` now lower-case
  `category`/`source` before querying (both are stored lower-case), so a display-cased
  value from a frontend dropdown no longer silently returns an empty result.
  `external_id` is deliberately left as-is since it's case-significant data.
- Encoded two previously-unwritten-but-confirmed crypto behaviors: a coin with only a price
  series (no market cap/volume) is returned, not dropped, with those fields `null`; a coin
  with a `NULL` market cap sorts last rather than first.

**Out of scope, deliberately deferred** (unchanged from before, plus confirmed still
applicable): the dashboard N+1 and its Neon cold-start floor; macro sparklines dropping
NULLs and `points` carrying no dates; sparkline labels using `external_id`/`symbol` instead
of `name`; `change_pct: 0.0` for a single-point series; `/v1/health` being edge-cached;
unbounded `/v1/prices`/observations payloads; default `operationId`s; inverted date ranges
returning `[]`; `date.today()` being server-local; the CORS `Vary: Origin` interaction with
edge caching; per-source in-flight locking on `/internal/ingest`; the dashboard duplicating
the status and earnings queries; `crypto.py` producing a phantom coin for a colon-less
`external_id`; `/internal/ingest/all` returning 404; the suite requiring a populated `.env`.
A shared `get_or_404` helper was also deliberately not extracted — Fix 3 above resolves the
divergence it would have existed to prevent.
