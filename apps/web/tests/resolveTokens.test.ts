import { describe, expect, it } from "vitest";

import { buildLineOption } from "@/charts/lineOption";
import { resolveCssVars, resolveToken } from "@/charts/resolveTokens";

const LIGHT: Record<string, string> = {
  "--series-1": "#2a78d6",
  "--series-2": "#eb6834",
  "--text-secondary": "#52514e",
  "--surface-1": "#fcfcfb",
  "--grid": "#e1e0d9",
  "--axis": "#c3c2b7",
  "--text-primary": "#0b0b0b",
  "--text-muted": "#898781",
  "--border": "rgba(11, 11, 11, 0.1)",
};

const DARK: Record<string, string> = {
  ...LIGHT,
  "--series-1": "#3987e5",
  "--series-2": "#d95926",
  "--surface-1": "#1a1a19",
  "--text-primary": "#ffffff",
};

const read = (table: Record<string, string>) => (name: string) => table[name] ?? "";

describe("resolveToken", () => {
  it("resolves a plain token", () => {
    expect(resolveToken("var(--series-1)", read(LIGHT))).toBe("#2a78d6");
  });

  it("tolerates whitespace inside the reference", () => {
    expect(resolveToken("var( --series-1 )", read(LIGHT))).toBe("#2a78d6");
  });

  it("leaves a literal color untouched", () => {
    expect(resolveToken("#ff0000", read(LIGHT))).toBe("#ff0000");
    expect(resolveToken("transparent", read(LIGHT))).toBe("transparent");
  });

  it("uses the declared fallback when the token is undefined", () => {
    expect(resolveToken("var(--nope, #123456)", read(LIGHT))).toBe("#123456");
  });

  it("resolves a fallback that is itself a token", () => {
    expect(resolveToken("var(--nope, var(--series-1))", read(LIGHT))).toBe("#2a78d6");
  });

  it("never returns an unresolved var(), which canvas would paint black", () => {
    const result = resolveToken("var(--missing)", read(LIGHT));
    expect(result).not.toContain("var(");
    expect(result).toBe("currentColor");
  });
});

describe("resolveCssVars", () => {
  it("walks nested objects and arrays", () => {
    const input = {
      series: [{ lineStyle: { color: "var(--series-1)", width: 2 } }],
      legend: { textStyle: { color: "var(--text-secondary)" } },
      animation: false,
      count: 3,
      nothing: null,
    };

    expect(resolveCssVars(input, read(LIGHT))).toEqual({
      series: [{ lineStyle: { color: "#2a78d6", width: 2 } }],
      legend: { textStyle: { color: "#52514e" } },
      animation: false,
      count: 3,
      nothing: null,
    });
  });

  it("does not mutate the input", () => {
    // Options are built in useMemo; mutating would bake one theme's colors
    // into the memoised object and the next toggle would not change them.
    const input = { color: "var(--series-1)" };
    resolveCssVars(input, read(LIGHT));
    expect(input.color).toBe("var(--series-1)");
  });

  it("leaves no var() anywhere in a real chart option", () => {
    const option = buildLineOption({
      series: [
        {
          id: "a",
          name: "A",
          color: "var(--series-1)",
          points: [["2026-09-01", 1]],
        },
        {
          id: "b",
          name: "B",
          color: "var(--series-2)",
          points: [["2026-09-01", 2]],
        },
      ],
    });

    const resolved = JSON.stringify(resolveCssVars(option, read(LIGHT)));
    expect(resolved).not.toContain("var(--");
  });

  it("yields different colors under the dark table, which is the whole point", () => {
    const option = buildLineOption({
      series: [
        { id: "a", name: "A", color: "var(--series-1)", points: [["2026-09-01", 1]] },
      ],
    });

    const light = resolveCssVars(option, read(LIGHT)) as {
      series: Array<{ lineStyle: { color: string } }>;
    };
    const dark = resolveCssVars(option, read(DARK)) as {
      series: Array<{ lineStyle: { color: string } }>;
    };

    expect(light.series[0].lineStyle.color).toBe("#2a78d6");
    expect(dark.series[0].lineStyle.color).toBe("#3987e5");
  });
});
