export interface AssetOut {
  symbol: string;
  name: string;
  exchange: string | null;
  sector: string | null;
}

export interface PriceBarOut {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface SeriesOut {
  source: string;
  external_id: string;
  name: string;
  unit: string | null;
  frequency: string | null;
  category: string;
}

export interface ObservationOut {
  obs_date: string;
  value: number | null;
}

export interface CoinOut {
  coin_id: string;
  name: string;
  price_usd: number | null;
  market_cap_usd: number | null;
  volume_24h_usd: number | null;
  as_of: string;
}

export interface FxConversionOut {
  from_currency: string;
  to_currency: string;
  amount: number;
  rate: number;
  result: number;
  rate_date: string;
}

export interface NewsOut {
  symbol: string;
  published_at: string;
  headline: string;
  source: string | null;
  url: string;
  summary: string | null;
  image_url: string | null;
}

export interface EarningsOut {
  symbol: string;
  report_date: string;
  hour: string | null;
  eps_estimate: number | null;
  eps_actual: number | null;
  revenue_estimate: number | null;
  revenue_actual: number | null;
}

export interface RatingOut {
  symbol: string;
  period: string;
  strong_buy: number | null;
  buy: number | null;
  hold: number | null;
  sell: number | null;
  strong_sell: number | null;
}

export type IngestStatus = "running" | "success" | "partial" | "failed";

export interface IngestRunOut {
  id: number;
  source: string;
  job: string;
  started_at: string;
  finished_at: string | null;
  status: IngestStatus;
  rows_upserted: number;
  api_calls_used: number;
  error: string | null;
}

export interface SparklineOut {
  label: string;
  latest: number | null;
  change_pct: number | null;
  points: number[];
}

export interface DashboardOut {
  generated_at: string;
  markets: SparklineOut[];
  macro: SparklineOut[];
  crypto: CoinOut[];
  upcoming_earnings: EarningsOut[];
  pipeline: IngestRunOut[];
}

export interface DateRange {
  from?: string;
  to?: string;
}
