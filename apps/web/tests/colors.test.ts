import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriesVar, useStableColors } from "@/lib/colors";

describe("seriesVar", () => {
  it("maps slot 0 to the first series token", () => {
    expect(seriesVar(0)).toBe("var(--series-1)");
  });

  it("wraps past the eighth slot rather than inventing a hue", () => {
    expect(seriesVar(8)).toBe("var(--series-1)");
  });
});

describe("useStableColors", () => {
  it("assigns slots in the order ids first appear", () => {
    const { result } = renderHook(() => useStableColors(["a", "b", "c"]));
    expect(result.current.get("a")).toBe("var(--series-1)");
    expect(result.current.get("b")).toBe("var(--series-2)");
    expect(result.current.get("c")).toBe("var(--series-3)");
  });

  it("keeps a survivor's color when an earlier id is removed", () => {
    const { result, rerender } = renderHook(({ ids }) => useStableColors(ids), {
      initialProps: { ids: ["a", "b", "c"] },
    });
    expect(result.current.get("c")).toBe("var(--series-3)");

    rerender({ ids: ["b", "c"] });
    expect(result.current.get("b")).toBe("var(--series-2)");
    expect(result.current.get("c")).toBe("var(--series-3)");
  });

  it("gives a newly added id the next free slot", () => {
    const { result, rerender } = renderHook(({ ids }) => useStableColors(ids), {
      initialProps: { ids: ["a"] },
    });
    rerender({ ids: ["a", "z"] });
    expect(result.current.get("a")).toBe("var(--series-1)");
    expect(result.current.get("z")).toBe("var(--series-2)");
  });
});
