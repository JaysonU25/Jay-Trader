import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useEffect, useRef } from "react";

import { useTheme } from "@/lib/theme";

echarts.use([
  LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer,
]);

export function Chart({
  option,
  height = 320,
  ariaLabel,
}: {
  option: EChartsOption;
  height?: number;
  ariaLabel: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.ECharts | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    instance.current = echarts.init(element, undefined, { renderer: "canvas" });
    const observer = new ResizeObserver(() => instance.current?.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.current?.dispose();
      instance.current = null;
    };
  }, []);

  useEffect(() => {
    // `theme` is a dependency because ECharts resolves CSS custom properties at
    // draw time — a theme switch needs a redraw to pick up the new values.
    instance.current?.setOption(option, { notMerge: true });
  }, [option, theme]);

  return <div ref={host} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />;
}
