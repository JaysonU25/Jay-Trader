import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useEffect, useRef } from "react";

import { useTheme } from "@/lib/theme";

import { documentTokenReader, resolveCssVars } from "./resolveTokens";

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
    // Tokens are resolved here, not by ECharts. The canvas renderer assigns
    // colors straight to strokeStyle/fillStyle, where `var(--series-1)` is not
    // a valid color and silently leaves the previous value — black — in place.
    //
    // `theme` is a dependency because the resolved values change with it: the
    // same token reads a different hex once data-theme flips, so the option has
    // to be re-resolved and redrawn.
    if (!instance.current) return;
    const resolved = resolveCssVars(option, documentTokenReader());
    instance.current.setOption(resolved, { notMerge: true });
  }, [option, theme]);

  return <div ref={host} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />;
}
