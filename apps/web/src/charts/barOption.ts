import type { EChartsOption } from "echarts";

import { sequentialVar } from "@/lib/colors";

import { baseOption, INK, valueAxis } from "./baseOption";

export interface BarInput {
  items: Array<{ label: string; value: number }>;
  valueName: string;
}

export function buildBarOption({ items, valueName }: BarInput): EChartsOption {
  // Ascending, because ECharts draws a horizontal category axis bottom-up:
  // the largest value ends up at the top of the chart where the eye starts.
  const sorted = [...items].sort((a, b) => a.value - b.value);
  const max = Math.max(...sorted.map((i) => i.value), 1);
  const base = baseOption();

  return {
    ...base,
    grid: { left: 8, right: 48, top: 16, bottom: 8, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "item" },
    xAxis: valueAxis(valueName),
    yAxis: {
      type: "category",
      data: sorted.map((i) => i.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: INK.secondary, fontSize: 12 },
    },
    series: [
      {
        type: "bar",
        name: valueName,
        data: sorted.map((i) => ({
          value: i.value,
          // Sequential shading: magnitude, not identity.
          itemStyle: { color: sequentialVar(i.value / max) },
        })),
        barMaxWidth: 18,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
      },
    ],
  };
}
