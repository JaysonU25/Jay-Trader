import { useMemo, useState } from "react";

import { Chart } from "@/charts/Chart";
import { buildLineOption, type LineSeries } from "@/charts/lineOption";
import { ChartFrame } from "@/components/ChartFrame";
import { DataTable } from "@/components/DataTable";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { useStableColors } from "@/lib/colors";
import { formatDate, formatNumber } from "@/lib/format";
import { useObservations, useSeries } from "@/lib/queries";
import type { ObservationOut, SeriesOut } from "@/lib/types";

const MACRO_CATEGORIES = ["rates", "inflation", "labor", "growth"];

/** Four is the direct-label ceiling from the dataviz rules, and also the number
 *  of observation hooks this component can call unconditionally. */
const MAX_SELECTED = 4;

function SeriesPanel({
  series,
  selected,
  onToggle,
}: {
  series: SeriesOut[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <fieldset className="card" style={{ marginBottom: 16, border: "1px solid var(--border)" }}>
      <legend style={{ color: "var(--text-secondary)", fontSize: 12 }}>Series</legend>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {series.map((s) => (
          <label key={s.external_id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={selected.includes(s.external_id)}
              onChange={() => onToggle(s.external_id)}
            />
            {s.name}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * React forbids conditional hook calls, so the overlay caps at four series and
 * calls exactly four observation hooks. The unused ones pass undefined, which
 * leaves their query disabled.
 */
function useSelectedObservations(selected: string[]): Record<string, ObservationOut[]> {
  const a = useObservations("fred", selected[0]);
  const b = useObservations("fred", selected[1]);
  const c = useObservations("fred", selected[2]);
  const d = useObservations("fred", selected[3]);

  return useMemo(() => {
    const out: Record<string, ObservationOut[]> = {};
    [a.data, b.data, c.data, d.data].forEach((data, i) => {
      const id = selected[i];
      if (id && data) out[id] = data;
    });
    return out;
  }, [a.data, b.data, c.data, d.data, selected]);
}

export function Macro() {
  const catalogue = useSeries();
  const [selected, setSelected] = useState<string[] | null>(null);

  const macroSeries = useMemo(
    () => (catalogue.data ?? []).filter((s) => MACRO_CATEGORIES.includes(s.category)),
    [catalogue.data],
  );

  // Default to the first series so the view is never blank on arrival. Once the
  // user touches a checkbox, `selected` takes over — including an empty array.
  const active = selected ?? (macroSeries.length > 0 ? [macroSeries[0].external_id] : []);
  const capped = useMemo(() => active.slice(0, MAX_SELECTED), [active]);
  const colors = useStableColors(capped);
  const observations = useSelectedObservations(capped);

  const toggle = (id: string) =>
    setSelected((current) => {
      const base = current ?? active;
      return base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
    });

  const lineSeries: LineSeries[] = capped.map((id) => ({
    id,
    name: macroSeries.find((s) => s.external_id === id)?.name ?? id,
    color: colors.get(id) ?? "var(--series-1)",
    points: (observations[id] ?? []).map((o) => [o.obs_date, o.value] as [string, number | null]),
  }));

  // Units differ across FRED series (Percent, Index, Thousands of Persons), so
  // any overlay of more than one must be indexed. A second y-axis is not an option.
  const indexed = lineSeries.length > 1;

  const dates = useMemo(
    () =>
      Array.from(new Set(capped.flatMap((id) => (observations[id] ?? []).map((o) => o.obs_date))))
        .sort()
        .reverse()
        .slice(0, 100),
    [capped, observations],
  );

  if (catalogue.isLoading) return <Loading label="Loading series catalogue" />;
  if (catalogue.isError) {
    return <ErrorState error={catalogue.error} onRetry={() => catalogue.refetch()} />;
  }

  const title = indexed ? "Indexed comparison" : (lineSeries[0]?.name ?? "");
  const unit = macroSeries.find((s) => s.external_id === capped[0])?.unit ?? undefined;

  return (
    <>
      <h1>Macro</h1>
      <SeriesPanel series={macroSeries} selected={capped} onToggle={toggle} />
      {capped.length === 0 ? (
        <EmptyState title="Select at least one series" hint="Pick up to four to overlay." />
      ) : (
        <ChartFrame
          title={title}
          chart={
            <Chart
              option={buildLineOption({
                series: lineSeries,
                indexed,
                yName: indexed ? undefined : unit,
              })}
              ariaLabel={title}
            />
          }
          table={
            <DataTable
              caption={title}
              columns={[
                { key: "date", header: "Date" },
                ...capped.map((id) => ({
                  key: id,
                  header: macroSeries.find((s) => s.external_id === id)?.name ?? id,
                  align: "right" as const,
                })),
              ]}
              rows={dates.map((date) => {
                const row: Record<string, string | number | null> = { date: formatDate(date) };
                for (const id of capped) {
                  const hit = (observations[id] ?? []).find((o) => o.obs_date === date);
                  row[id] = hit && hit.value !== null ? formatNumber(hit.value) : null;
                }
                return row;
              })}
            />
          }
        />
      )}
    </>
  );
}
