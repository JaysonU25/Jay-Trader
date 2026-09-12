import type { EChartsOption } from "echarts";

import { baseOption, INK, timeAxis, valueAxis } from "./baseOption";

export interface LineSeries {
  id: string;
  name: string;
  color: string;
  points: Array<[string, number | null]>;
}

export interface LineInput {
  series: LineSeries[];
  yName?: string;
  /** Rebase every series to 100 at its first non-null point. */
  indexed?: boolean;
}

const DIRECT_LABEL_MAX = 4;

function rebase(points: Array<[string, number | null]>): Array<[string, number | null]> {
  const first = points.find(([, v]) => v !== null && v !== 0)?.[1];
  if (first === undefined || first === null) return points;
  return points.map(([d, v]) => [d, v === null ? null : (v / first) * 100]);
}

export function buildLineOption({ series, yName, indexed = false }: LineInput): EChartsOption {
  const directLabel = series.length <= DIRECT_LABEL_MAX;
  const base = baseOption();

  return {
    ...base,
    legend: {
      show: series.length >= 2,
      bottom: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: INK.secondary, fontSize: 12 },
    },
    tooltip: {
      ...base.tooltip,
      trigger: "axis",
      axisPointer: { type: "cross", label: { show: false }, crossStyle: { color: INK.axis } },
    },
    xAxis: timeAxis(),
    yAxis: valueAxis(indexed ? "Indexed to 100" : yName),
    series: series.map((s) => ({
      id: s.id,
      name: s.name,
      type: "line" as const,
      data: indexed ? rebase(s.points) : s.points,
      connectNulls: false,
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, color: s.color },
      itemStyle: { color: s.color, borderWidth: 2, borderColor: INK.surface },
      emphasis: { focus: "series" as const },
      endLabel: {
        show: directLabel,
        color: INK.secondary,
        fontSize: 11,
        formatter: s.name,
      },
    })),
  };
}
