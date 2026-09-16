import { useState } from "react";

import { DataTable } from "@/components/DataTable";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { useAssets, useNews, useUpcomingEarnings } from "@/lib/queries";

const HOUR_LABEL: Record<string, string> = {
  bmo: "Before market open",
  amc: "After market close",
  dmh: "During market hours",
};

/** Empty string means "no filter"; a <select> value cannot be undefined. */
const ALL = "";

export function NewsEarnings() {
  const [symbol, setSymbol] = useState<string>(ALL);

  const assets = useAssets();
  const news = useNews(symbol || undefined, 50);
  const earnings = useUpcomingEarnings(90);

  // The dropdown is a convenience over the feed. If the asset list fails or is
  // still loading, fall back to an empty option list rather than blocking the
  // news behind it.
  const options = assets.data ?? [];

  return (
    <>
      <h1>News &amp; Earnings</h1>

      <section className="card" style={{ marginBottom: 16 }}>
        <h2>Upcoming earnings</h2>
        {earnings.isLoading ? <Loading /> : null}
        {earnings.isError ? (
          <ErrorState error={earnings.error} onRetry={() => earnings.refetch()} />
        ) : null}
        {earnings.data ? (
          <DataTable
            caption="Next 90 days"
            columns={[
              { key: "symbol", header: "Symbol" },
              { key: "date", header: "Date" },
              { key: "hour", header: "When" },
              { key: "eps_estimate", header: "EPS est.", align: "right" },
              { key: "eps_actual", header: "EPS actual", align: "right" },
            ]}
            rows={earnings.data.map((e) => ({
              symbol: e.symbol,
              date: formatDate(e.report_date),
              hour: e.hour ? (HOUR_LABEL[e.hour] ?? e.hour) : null,
              eps_estimate: e.eps_estimate === null ? null : formatNumber(e.eps_estimate),
              eps_actual: e.eps_actual === null ? null : formatNumber(e.eps_actual),
            }))}
          />
        ) : null}
      </section>

      <section className="card">
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <h2 style={{ margin: 0 }}>Latest news</h2>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            Symbol
            <select
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              style={{ minWidth: 140 }}
            >
              <option value={ALL}>All symbols</option>
              {options.map((asset) => (
                <option key={asset.symbol} value={asset.symbol}>
                  {asset.symbol}
                </option>
              ))}
            </select>
          </label>
        </header>

        <div style={{ marginTop: 12 }}>
          {news.isLoading ? <Loading /> : null}
          {news.isError ? <ErrorState error={news.error} onRetry={() => news.refetch()} /> : null}

          {news.data && news.data.length === 0 ? (
            <EmptyState
              title={symbol ? `No news for ${symbol}` : "No news yet"}
              hint={
                symbol
                  ? "Finnhub returned nothing for this symbol in the ingested window."
                  : undefined
              }
            />
          ) : null}

          {news.data && news.data.length > 0 ? (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {news.data.map((item) => (
                <li
                  key={item.url}
                  style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}
                >
                  <a href={item.url} target="_blank" rel="noopener noreferrer">
                    {item.headline}
                  </a>
                  <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 2 }}>
                    {`${item.symbol}${item.source ? ` · ${item.source}` : ""} · ${formatDateTime(
                      item.published_at,
                    )}`}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </section>
    </>
  );
}
