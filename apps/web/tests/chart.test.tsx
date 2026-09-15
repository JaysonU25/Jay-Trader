import { render } from "@testing-library/react";
import * as echarts from "echarts/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chart } from "@/charts/Chart";
import { buildLineOption } from "@/charts/lineOption";

function option() {
  return buildLineOption({
    series: [
      { id: "a", name: "A", color: "var(--series-1)", points: [["2026-09-01", 1]] },
      { id: "b", name: "B", color: "var(--series-2)", points: [["2026-09-01", 2]] },
    ],
  });
}

function lastSetOption(): unknown {
  const init = echarts.init as unknown as ReturnType<typeof vi.fn>;
  const instance = init.mock.results.at(-1)?.value as {
    setOption: ReturnType<typeof vi.fn>;
  };
  return instance.setOption.mock.calls.at(-1)?.[0];
}

afterEach(() => {
  document.documentElement.style.cssText = "";
  vi.clearAllMocks();
});

describe("Chart", () => {
  it("never hands ECharts an unresolved var(), which canvas paints black", () => {
    // The regression this guards: the canvas renderer assigns colors straight
    // to strokeStyle, where var(--series-1) is not a valid color, so every
    // series drew black in both themes.
    render(<Chart option={option()} ariaLabel="test chart" />);

    expect(JSON.stringify(lastSetOption())).not.toContain("var(--");
  });

  it("resolves tokens to the values currently on the document root", () => {
    document.documentElement.style.setProperty("--series-1", "#2a78d6");
    document.documentElement.style.setProperty("--series-2", "#eb6834");

    render(<Chart option={option()} ariaLabel="test chart" />);

    const sent = lastSetOption() as { series: Array<{ lineStyle: { color: string } }> };
    expect(sent.series[0].lineStyle.color).toBe("#2a78d6");
    expect(sent.series[1].lineStyle.color).toBe("#eb6834");
  });

  it("exposes the chart to assistive tech with its label", () => {
    const { getByRole } = render(<Chart option={option()} ariaLabel="close price" />);
    expect(getByRole("img", { name: "close price" })).toBeInTheDocument();
  });
});
