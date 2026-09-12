import { useMemo, useState } from "react";

import { Chart } from "@/charts/Chart";
import { buildLineOption } from "@/charts/lineOption";
import { ChartFrame } from "@/components/ChartFrame";
import { DataTable } from "@/components/DataTable";
import { ErrorState, Loading } from "@/components/States";
import { formatDate, formatNumber } from "@/lib/format";
import { useFxConvert, useObservations } from "@/lib/queries";

export function Fx() {
  const [from, setFrom] = useState("USD");
  const [to, setTo] = useState("JPY");
  const [amount, setAmount] = useState(100);

  const conversion = useFxConvert({ from, to, amount });
  // History is always shown against the EUR base, which is what the API stores;
  // USD to JPY is served as a cross-rate but only EUR pairs exist as series.
  const history = useObservations("frankfurter", `EUR/${to}`);

  const option = useMemo(
    () =>
      buildLineOption({
        series: [
          {
            id: `EUR/${to}`,
            name: `EUR to ${to}`,
            color: "var(--series-1)",
            points: (history.data ?? []).map(
              (o) => [o.obs_date, o.value] as [string, number | null],
            ),
          },
        ],
        yName: "Rate",
      }),
    [history.data, to],
  );

  return (
    <>
      <h1>FX</h1>

      <section className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ display: "grid", gap: 4 }}>
            Amount
            <input
              type="number"
              value={amount}
              min={0}
              onChange={(e) => setAmount(Number(e.target.value))}
              style={{ width: 120 }}
            />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            From
            <input
              value={from}
              maxLength={3}
              onChange={(e) => setFrom(e.target.value.toUpperCase())}
              style={{ width: 80 }}
            />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            To
            <input
              value={to}
              maxLength={3}
              onChange={(e) => setTo(e.target.value.toUpperCase())}
              style={{ width: 80 }}
            />
          </label>
        </div>

        <div style={{ marginTop: 16 }}>
          {conversion.isLoading ? <Loading label="Converting" /> : null}
          {conversion.isError ? <ErrorState error={conversion.error} /> : null}
          {conversion.data ? (
            <>
              <div style={{ fontSize: 28 }}>
                {`${formatNumber(conversion.data.result)} ${conversion.data.to_currency}`}
              </div>
              <div style={{ color: "var(--text-secondary)", fontSize: 12, marginTop: 4 }}>
                {`1 ${conversion.data.from_currency} = ${formatNumber(conversion.data.rate, 4)} ${
                  conversion.data.to_currency
                } · ${formatDate(conversion.data.rate_date)}`}
              </div>
            </>
          ) : null}
        </div>
      </section>

      {history.isError ? (
        <ErrorState error={history.error} onRetry={() => history.refetch()} />
      ) : (
        <ChartFrame
          title={`EUR to ${to}`}
          chart={<Chart option={option} ariaLabel={`EUR to ${to} rate history`} />}
          table={
            <DataTable
              caption={`EUR to ${to}`}
              columns={[
                { key: "date", header: "Date" },
                { key: "rate", header: "Rate", align: "right" },
              ]}
              rows={(history.data ?? [])
                .slice(-100)
                .reverse()
                .map((o) => ({
                  date: formatDate(o.obs_date),
                  rate: o.value === null ? null : formatNumber(o.value, 4),
                }))}
            />
          }
        />
      )}
    </>
  );
}
