import { useMemo, useState } from "react";

import { Chart } from "@/charts/Chart";
import { buildLineOption } from "@/charts/lineOption";
import { ChartFrame } from "@/components/ChartFrame";
import { DataTable } from "@/components/DataTable";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { formatCompact, formatDate, formatNumber } from "@/lib/format";
import { useAssets, usePrices } from "@/lib/queries";

export function Markets() {
  const assets = useAssets();
  const [symbol, setSymbol] = useState<string | undefined>();

  const active = symbol ?? assets.data?.[0]?.symbol;
  const prices = usePrices(active);

  const option = useMemo(
    () =>
      buildLineOption({
        series: [
          {
            id: active ?? "none",
            name: `${active ?? ""} close`,
            color: "var(--series-1)",
            points: (prices.data ?? []).map(
              (b) => [b.trade_date, b.close] as [string, number | null],
            ),
          },
        ],
        yName: "Close",
      }),
    [prices.data, active],
  );

  if (assets.isLoading) return <Loading label="Loading assets" />;
  if (assets.isError) return <ErrorState error={assets.error} onRetry={() => assets.refetch()} />;

  if ((assets.data ?? []).length === 0) {
    return (
      <>
        <h1>Markets</h1>
        <EmptyState
          title="No equities ingested yet"
          hint="Alpha Vantage moved outputsize=full to its premium tier, so the price backfill has not run. See docs/FOLLOWUPS.md."
        />
      </>
    );
  }

  return (
    <>
      <h1>Markets</h1>

      <label style={{ display: "grid", gap: 4, marginBottom: 16, maxWidth: 320 }}>
        Symbol
        <select value={active} onChange={(e) => setSymbol(e.target.value)}>
          {(assets.data ?? []).map((a) => (
            <option key={a.symbol} value={a.symbol}>
              {a.name}
            </option>
          ))}
        </select>
      </label>

      <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 0 }}>
        Prices are unadjusted for splits — Alpha Vantage&apos;s free tier returns raw OHLCV.
      </p>

      {prices.isError ? (
        <ErrorState error={prices.error} onRetry={() => prices.refetch()} />
      ) : (
        <ChartFrame
          title={`${active} close`}
          chart={<Chart option={option} ariaLabel={`${active} close price`} />}
          table={
            <DataTable
              caption={`${active} daily bars`}
              columns={[
                { key: "date", header: "Date" },
                { key: "open", header: "Open", align: "right" },
                { key: "high", header: "High", align: "right" },
                { key: "low", header: "Low", align: "right" },
                { key: "close", header: "Close", align: "right" },
                { key: "volume", header: "Volume", align: "right" },
              ]}
              rows={(prices.data ?? [])
                .slice()
                .reverse()
                .map((b) => ({
                  date: formatDate(b.trade_date),
                  open: formatNumber(b.open),
                  high: formatNumber(b.high),
                  low: formatNumber(b.low),
                  close: formatNumber(b.close),
                  volume: b.volume === null ? null : formatCompact(b.volume),
                }))}
            />
          }
        />
      )}
    </>
  );
}
