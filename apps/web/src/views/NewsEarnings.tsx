import { DataTable } from "@/components/DataTable";
import { ErrorState, Loading } from "@/components/States";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { useNews, useUpcomingEarnings } from "@/lib/queries";

const HOUR_LABEL: Record<string, string> = {
  bmo: "Before market open",
  amc: "After market close",
  dmh: "During market hours",
};

export function NewsEarnings() {
  const news = useNews(undefined, 50);
  const earnings = useUpcomingEarnings(90);

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
        <h2>Latest news</h2>
        {news.isLoading ? <Loading /> : null}
        {news.isError ? <ErrorState error={news.error} onRetry={() => news.refetch()} /> : null}
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {(news.data ?? []).map((item) => (
            <li key={item.url} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
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
      </section>
    </>
  );
}
