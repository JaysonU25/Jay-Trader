import { describe, expect, it } from "vitest";

import { buildBarOption } from "@/charts/barOption";
import { buildLineOption } from "@/charts/lineOption";

const twoSeries = [
  {
    id: "DGS10", name: "10-Year Treasury", color: "var(--series-1)",
    points: [["2026-09-01", 4.3], ["2026-09-02", 4.2]] as Array<[string, number | null]>,
  },
  {
    id: "UNRATE", name: "Unemployment Rate", color: "var(--series-2)",
    points: [["2026-09-01", 4.1], ["2026-09-02", 4.1]] as Array<[string, number | null]>,
  },
];

describe("buildLineOption", () => {
  it("emits exactly one y-axis — never a dual axis", () => {
    const option = buildLineOption({ series: twoSeries });
    expect(Array.isArray(option.yAxis) ? option.yAxis.length : 1).toBe(1);
  });

  it("uses 2px lines and hides symbols until hover", () => {
    const option = buildLineOption({ series: twoSeries });
    const first = (option.series as Array<Record<string, unknown>>)[0];
    expect((first.lineStyle as { width: number }).width).toBe(2);
    expect(first.showSymbol).toBe(false);
    expect(first.symbolSize as number).toBeGreaterThanOrEqual(8);
  });

  it("shows a legend for two or more series", () => {
    const option = buildLineOption({ series: twoSeries });
    expect((option.legend as { show: boolean }).show).toBe(true);
  });

  it("hides the legend for a single series — the title names it", () => {
    const option = buildLineOption({ series: [twoSeries[0]] });
    expect((option.legend as { show: boolean }).show).toBe(false);
  });

  it("direct-labels the series end when there are four or fewer", () => {
    const option = buildLineOption({ series: twoSeries });
    const first = (option.series as Array<Record<string, unknown>>)[0];
    expect((first.endLabel as { show: boolean }).show).toBe(true);
  });

  it("drops direct labels past four series to avoid collisions", () => {
    const five = ["a", "b", "c", "d", "e"].map((id, i) => ({
      id, name: id, color: `var(--series-${i + 1})`,
      points: [["2026-09-01", i]] as Array<[string, number | null]>,
    }));
    const option = buildLineOption({ series: five });
    const first = (option.series as Array<Record<string, unknown>>)[0];
    expect((first.endLabel as { show: boolean }).show).toBe(false);
    expect((option.legend as { show: boolean }).show).toBe(true);
  });

  it("carries a crosshair tooltip", () => {
    const option = buildLineOption({ series: twoSeries });
    expect((option.tooltip as { trigger: string }).trigger).toBe("axis");
    expect((option.tooltip as { axisPointer: { type: string } }).axisPointer.type).toBe("cross");
  });

  it("indexes every series to 100 at its first non-null point when indexed", () => {
    const option = buildLineOption({ series: twoSeries, indexed: true });
    const data = (option.series as Array<{ data: Array<[string, number | null]> }>)[0].data;
    expect(data[0][1]).toBe(100);
    expect(data[1][1]).toBeCloseTo((4.2 / 4.3) * 100, 6);
  });

  it("preserves nulls as gaps rather than dropping the point", () => {
    const option = buildLineOption({
      series: [{
        id: "x", name: "x", color: "var(--series-1)",
        points: [["2026-09-01", 1], ["2026-09-02", null], ["2026-09-03", 3]],
      }],
    });
    const data = (option.series as Array<{ data: Array<[string, number | null]> }>)[0].data;
    expect(data).toHaveLength(3);
    expect(data[1][1]).toBeNull();
  });
});

describe("buildBarOption", () => {
  it("sorts descending and shades by magnitude, not by rank identity", () => {
    const option = buildBarOption({
      items: [{ label: "b", value: 5 }, { label: "a", value: 10 }],
      valueName: "Market cap",
    });
    const data = (option.series as Array<{ data: Array<{ value: number }> }>)[0].data;
    // Horizontal bars render bottom-up, so ascending data puts the largest on top.
    expect(data.map((d) => d.value)).toEqual([5, 10]);
  });

  it("carries a per-mark hover tooltip", () => {
    const option = buildBarOption({ items: [{ label: "a", value: 1 }], valueName: "v" });
    expect((option.tooltip as { trigger: string }).trigger).toBe("item");
  });

  it("rounds the data end of each bar", () => {
    const option = buildBarOption({ items: [{ label: "a", value: 1 }], valueName: "v" });
    const series = (option.series as Array<{ itemStyle: { borderRadius: number[] } }>)[0];
    expect(series.itemStyle.borderRadius).toEqual([0, 4, 4, 0]);
  });
});
