import { useMemo } from "react";

import { Chart } from "@/charts/Chart";
import { buildBarOption } from "@/charts/barOption";
import { ChartFrame } from "@/components/ChartFrame";
import { DataTable } from "@/components/DataTable";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { formatCompact, formatNumber } from "@/lib/format";
import { useTopCoins } from "@/lib/queries";

export function Crypto() {
  const coins = useTopCoins(20);

  const ranked = useMemo(
    () =>
      (coins.data ?? [])
        .filter((c) => c.market_cap_usd !== null)
        .sort((a, b) => (b.market_cap_usd ?? 0) - (a.market_cap_usd ?? 0)),
    [coins.data],
  );

  const total = ranked.reduce((sum, c) => sum + (c.market_cap_usd ?? 0), 0);
  const dominance = total > 0 && ranked[0] ? ((ranked[0].market_cap_usd ?? 0) / total) * 100 : null;

  const option = useMemo(
    () =>
      buildBarOption({
        items: ranked.map((c) => ({ label: c.name, value: c.market_cap_usd ?? 0 })),
        valueName: "Market cap (USD)",
      }),
    [ranked],
  );

  if (coins.isLoading) return <Loading label="Loading crypto" />;
  if (coins.isError) return <ErrorState error={coins.error} onRetry={() => coins.refetch()} />;

  if (ranked.length === 0) {
    return (
      <>
        <h1>Crypto</h1>
        <EmptyState
          title="No crypto data yet"
          hint="CoinGecko's market_chart endpoint returns 401 without an API key. See docs/FOLLOWUPS.md."
        />
      </>
    );
  }

  return (
    <>
      <h1>Crypto</h1>

      <div className="tile-grid" style={{ marginBottom: 16 }}>
        <StatTile
          label={`${ranked[0].name} dominance`}
          value={dominance === null ? "—" : `${dominance.toFixed(2)}%`}
        />
        <StatTile label="Total market cap (top 20)" value={formatCompact(total)} />
        <StatTile label="Coins tracked" value={String(ranked.length)} />
      </div>

      <ChartFrame
        title="Market cap by coin"
        chart={
          <Chart
            option={option}
            height={Math.max(240, ranked.length * 24)}
            ariaLabel="Market cap by coin"
          />
        }
        table={
          <DataTable
            caption="Top coins by market cap"
            columns={[
              { key: "name", header: "Coin" },
              { key: "price", header: "Price (USD)", align: "right" },
              { key: "cap", header: "Market cap", align: "right" },
              { key: "volume", header: "24h volume", align: "right" },
            ]}
            rows={ranked.map((c) => ({
              name: c.name,
              price: formatNumber(c.price_usd),
              cap: formatCompact(c.market_cap_usd),
              volume: formatCompact(c.volume_24h_usd),
            }))}
          />
        }
      />
    </>
  );
}
