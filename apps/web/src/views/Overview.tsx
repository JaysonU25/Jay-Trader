import { EmptyState, ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { StatusBadge } from "@/components/StatusBadge";
import { formatCompact, formatDate, formatNumber } from "@/lib/format";
import { useDashboard } from "@/lib/queries";
import type { SparklineOut } from "@/lib/types";

function TileRow({ items }: { items: SparklineOut[] }) {
  return (
    <div className="tile-grid">
      {items.map((s) => (
        <StatTile
          key={s.label}
          label={s.label}
          value={formatNumber(s.latest)}
          delta={s.change_pct}
          points={s.points}
        />
      ))}
    </div>
  );
}

export function Overview() {
  const dash = useDashboard();

  if (dash.isLoading) return <Loading label="Loading dashboard" />;
  if (dash.isError) return <ErrorState error={dash.error} onRetry={() => dash.refetch()} />;
  if (!dash.data) return <EmptyState title="No dashboard data" />;

  const data = dash.data;

  return (
    <>
      <h1>Overview</h1>

      <section style={{ marginBottom: 24 }}>
        <h2>Markets</h2>
        {data.markets.length === 0 ? (
          <EmptyState
            title="No equity data"
            hint="The Alpha Vantage price backfill has not completed."
          />
        ) : (
          <TileRow items={data.markets} />
        )}
      </section>

      <section style={{ marginBottom: 24 }}>
        <h2>Macro</h2>
        {data.macro.length === 0 ? (
          <EmptyState title="No macro data" />
        ) : (
          <TileRow items={data.macro} />
        )}
      </section>

      <section style={{ marginBottom: 24 }}>
        <h2>Crypto</h2>
        {data.crypto.length === 0 ? (
          <EmptyState title="No crypto data" hint="CoinGecko history requires an API key." />
        ) : (
          <div className="tile-grid">
            {data.crypto.map((c) => (
              <StatTile key={c.coin_id} label={c.name} value={formatCompact(c.market_cap_usd)} />
            ))}
          </div>
        )}
      </section>

      <section style={{ marginBottom: 24 }}>
        <h2>Upcoming earnings</h2>
        {data.upcoming_earnings.length === 0 ? (
          <EmptyState title="Nothing scheduled" />
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data.upcoming_earnings.map((e) => (
              <li
                key={`${e.symbol}-${e.report_date}`}
                style={{ padding: "6px 0", color: "var(--text-secondary)" }}
              >
                <strong style={{ color: "var(--text-primary)" }}>{e.symbol}</strong>
                {` · ${formatDate(e.report_date)}`}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2>Pipeline</h2>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {data.pipeline.map((run) => (
            <li
              key={run.id}
              style={{ padding: "6px 0", display: "flex", gap: 12, alignItems: "center" }}
            >
              <StatusBadge status={run.status} />
              <span style={{ color: "var(--text-secondary)" }}>
                {`${run.job} · ${run.rows_upserted.toLocaleString()} rows`}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
