import type {
  CoinOut, DashboardOut, EarningsOut, IngestRunOut, NewsOut,
  ObservationOut, PriceBarOut, RatingOut, SeriesOut,
} from "@/lib/types";

export const fxSeries: SeriesOut[] = [
  { source: "frankfurter", external_id: "EUR/USD", name: "EUR to USD", unit: "rate", frequency: "D", category: "fx" },
  { source: "frankfurter", external_id: "EUR/JPY", name: "EUR to JPY", unit: "rate", frequency: "D", category: "fx" },
];

export const macroSeries: SeriesOut[] = [
  { source: "fred", external_id: "CPIAUCSL", name: "Consumer Price Index", unit: "Index 1982-84=100", frequency: "M", category: "inflation" },
  { source: "fred", external_id: "UNRATE", name: "Unemployment Rate", unit: "Percent", frequency: "M", category: "labor" },
  { source: "fred", external_id: "DGS10", name: "10-Year Treasury", unit: "Percent", frequency: "D", category: "rates" },
];

export const observations: ObservationOut[] = [
  { obs_date: "2026-09-01", value: 100 },
  { obs_date: "2026-09-02", value: 102 },
  { obs_date: "2026-09-03", value: null },
  { obs_date: "2026-09-04", value: 105 },
];

export const bars: PriceBarOut[] = [
  { trade_date: "2026-09-01", open: 500, high: 505, low: 498, close: 503, volume: 1000000 },
  { trade_date: "2026-09-02", open: 503, high: 512, low: 502, close: 511, volume: 1200000 },
];

export const coins: CoinOut[] = [
  { coin_id: "bitcoin", name: "Bitcoin", price_usd: 95000, market_cap_usd: 1900000000000, volume_24h_usd: 40000000000, as_of: "2026-09-08" },
  { coin_id: "ethereum", name: "Ethereum", price_usd: 4200, market_cap_usd: 500000000000, volume_24h_usd: 20000000000, as_of: "2026-09-08" },
];

export const news: NewsOut[] = [
  { symbol: "AAPL", published_at: "2026-09-08T14:00:00Z", headline: "Apple ships something", source: "Reuters", url: "https://example.com/a", summary: "A summary.", image_url: null },
  { symbol: "MSFT", published_at: "2026-09-07T09:30:00Z", headline: "Microsoft does a thing", source: "Bloomberg", url: "https://example.com/b", summary: null, image_url: null },
];

export const earnings: EarningsOut[] = [
  { symbol: "AAPL", report_date: "2026-09-20", hour: "amc", eps_estimate: 2.1, eps_actual: null, revenue_estimate: 95000000000, revenue_actual: null },
];

export const ratings: RatingOut[] = [
  { symbol: "AAPL", period: "2026-09-01", strong_buy: 13, buy: 24, hold: 7, sell: 1, strong_sell: 0 },
];

export const runs: IngestRunOut[] = [
  { id: 9, source: "alphavantage", job: "prices", started_at: "2026-09-09T22:00:00Z", finished_at: "2026-09-09T22:00:04Z", status: "partial", rows_upserted: 0, api_calls_used: 1, error: "SPY: outputsize=full is a premium feature" },
  { id: 8, source: "fred", job: "macro", started_at: "2026-09-09T13:15:00Z", finished_at: "2026-09-09T13:16:10Z", status: "success", rows_upserted: 89819, api_calls_used: 30, error: null },
];

export const dashboard: DashboardOut = {
  generated_at: "2026-09-09T12:00:00Z",
  markets: [],
  macro: [
    { label: "10-Year Treasury", latest: 4.12, change_pct: -1.4, points: [4.3, 4.25, 4.18, 4.12] },
    { label: "Unemployment Rate", latest: 4.1, change_pct: 0, points: [4.1, 4.1, 4.1, 4.1] },
  ],
  crypto: [],
  upcoming_earnings: earnings,
  pipeline: runs,
};
