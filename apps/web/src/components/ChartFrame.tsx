import { useState, type ReactNode } from "react";

/**
 * Wraps every chart with a table toggle. This is not a convenience: three
 * light-mode palette slots fall below 3:1 contrast on the chart surface, and
 * the dataviz relief rule requires a text alternative wherever they are used.
 */
export function ChartFrame({
  title,
  chart,
  table,
}: {
  title: string;
  chart: ReactNode;
  table: ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");

  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>{title}</h2>
        <div role="group" aria-label={`${title} view`}>
          <button type="button" aria-pressed={view === "chart"} onClick={() => setView("chart")}>
            Chart
          </button>
          <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}>
            Table
          </button>
        </div>
      </header>
      <div style={{ marginTop: 12 }}>{view === "chart" ? chart : table}</div>
    </section>
  );
}
