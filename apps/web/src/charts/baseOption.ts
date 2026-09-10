import type { EChartsOption } from "echarts";

export const INK = {
  primary: "var(--text-primary)",
  secondary: "var(--text-secondary)",
  muted: "var(--text-muted)",
  grid: "var(--grid)",
  axis: "var(--axis)",
  surface: "var(--surface-1)",
  border: "var(--border)",
} as const;

export function baseOption(): EChartsOption {
  return {
    backgroundColor: "transparent",
    animation: false,
    grid: { left: 8, right: 64, top: 24, bottom: 8, containLabel: true },
    textStyle: {
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
      color: INK.secondary,
    },
    tooltip: {
      backgroundColor: INK.surface,
      borderColor: INK.border,
      textStyle: { color: INK.primary, fontSize: 12 },
      extraCssText: "box-shadow: 0 2px 8px rgba(0,0,0,0.12); border-radius: 6px;",
    },
  };
}

export function timeAxis() {
  return {
    type: "time" as const,
    axisLine: { lineStyle: { color: INK.axis } },
    axisTick: { show: false },
    axisLabel: { color: INK.muted, fontSize: 11 },
    splitLine: { show: false },
  };
}

export function valueAxis(name?: string) {
  return {
    type: "value" as const,
    name,
    nameTextStyle: { color: INK.muted, fontSize: 11, align: "left" as const },
    scale: true,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: INK.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: INK.grid, width: 1 } },
  };
}
