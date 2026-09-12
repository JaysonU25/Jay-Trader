import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./api";
import type {
  AssetOut, CoinOut, DashboardOut, DateRange, EarningsOut, FxConversionOut,
  IngestRunOut, NewsOut, ObservationOut, PriceBarOut, RatingOut, SeriesOut,
} from "./types";

// Matches the API's Cache-Control: public, s-maxage=3600. Data updates at most
// daily, so refetching more often than the edge cache turns over is pure waste.
const STALE_TIME = 5 * 60 * 1000;

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiGet<DashboardOut>("/v1/dashboard"),
    staleTime: STALE_TIME,
  });
}

export function useAssets() {
  return useQuery({
    queryKey: ["assets"],
    queryFn: () => apiGet<AssetOut[]>("/v1/assets"),
    staleTime: STALE_TIME,
  });
}

export function usePrices(symbol: string | undefined, range: DateRange = {}) {
  return useQuery({
    queryKey: ["prices", symbol, range.from, range.to],
    queryFn: () =>
      apiGet<PriceBarOut[]>(`/v1/prices/${symbol}`, { from: range.from, to: range.to }),
    enabled: Boolean(symbol),
    staleTime: STALE_TIME,
  });
}

export function useSeries(category?: string) {
  return useQuery({
    queryKey: ["series", category],
    queryFn: () => apiGet<SeriesOut[]>("/v1/series", { category }),
    staleTime: STALE_TIME,
  });
}

export function useObservations(
  source: string | undefined,
  externalId: string | undefined,
  range: DateRange = {},
) {
  return useQuery({
    queryKey: ["observations", source, externalId, range.from, range.to],
    // external_id is a :path param — EUR/USD and bitcoin:price go in raw.
    queryFn: () =>
      apiGet<ObservationOut[]>(`/v1/series/${source}/${externalId}/observations`, {
        from: range.from,
        to: range.to,
      }),
    enabled: Boolean(source && externalId),
    staleTime: STALE_TIME,
  });
}

export function useTopCoins(limit = 20) {
  return useQuery({
    queryKey: ["crypto", limit],
    queryFn: () => apiGet<CoinOut[]>("/v1/crypto/top", { limit }),
    staleTime: STALE_TIME,
  });
}

export function useFxConvert(params: {
  from: string;
  to: string;
  amount: number;
  date?: string;
}) {
  return useQuery({
    queryKey: ["fx", params.from, params.to, params.amount, params.date],
    queryFn: () => apiGet<FxConversionOut>("/v1/fx/convert", { ...params }),
    enabled: params.from.length === 3 && params.to.length === 3 && params.amount > 0,
    staleTime: STALE_TIME,
  });
}

export function useNews(symbol?: string, limit = 50) {
  return useQuery({
    queryKey: ["news", symbol, limit],
    queryFn: () => apiGet<NewsOut[]>("/v1/news", { symbol, limit }),
    staleTime: STALE_TIME,
  });
}

export function useUpcomingEarnings(days = 14) {
  return useQuery({
    queryKey: ["earnings", days],
    queryFn: () => apiGet<EarningsOut[]>("/v1/earnings/upcoming", { days }),
    staleTime: STALE_TIME,
  });
}

export function useRatings(symbol: string | undefined) {
  return useQuery({
    queryKey: ["ratings", symbol],
    queryFn: () => apiGet<RatingOut[]>(`/v1/ratings/${symbol}`),
    enabled: Boolean(symbol),
    staleTime: STALE_TIME,
  });
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<IngestRunOut[]>("/v1/status"),
    staleTime: 60 * 1000,
  });
}
