import { useMemo } from "react";

import { Chart } from "@/charts/Chart";
import { baseOption, INK } from "@/charts/baseOption";

/**
 * A tile with a plot gets a hover layer — only a bare stat tile skips it. The
 * axis is present but invisible so the tooltip has something to snap to.
 */
export function Sparkline({ points, label }: { points: number[]; label: string }) {
  const option = useMemo(() => {
    const base = baseOption();
    return {
      ...base,
      grid: { left: 0, right: 0, top: 4, bottom: 4 },
      tooltip: {
        ...base.tooltip,
        trigger: "axis" as const,
        axisPointer: { type: "none" as const },
      },
      xAxis: {
        type: "category" as const,
        show: true,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        data: points.map((_, i) => String(i)),
      },
      yAxis: { type: "value" as const, show: false, scale: true },
      series: [
        {
          type: "line" as const,
          name: label,
          data: points,
          showSymbol: false,
          symbolSize: 8,
          lineStyle: { width: 2, color: "var(--series-1)" },
          itemStyle: { color: "var(--series-1)", borderWidth: 2, borderColor: INK.surface },
        },
      ],
    };
  }, [points, label]);

  if (points.length === 0) return null;
  return <Chart option={option} height={40} ariaLabel={`${label} trend`} />;
}
