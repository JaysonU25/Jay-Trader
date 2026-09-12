import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";

import { resetThemeStore } from "@/lib/theme";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "./msw/handlers";

// ECharts needs a canvas 2D context, which jsdom does not implement. The chart
// logic that matters lives in the pure option builders (charts/*Option.ts) and
// is unit-tested directly; the wrapper only needs to mount and dispose without
// throwing, so a stub instance is the right double here.
vi.mock("echarts/core", () => {
  const instance = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  };
  return {
    init: vi.fn(() => instance),
    use: vi.fn(),
  };
});

vi.mock("echarts/charts", () => ({ BarChart: {}, LineChart: {} }));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  LegendComponent: {},
  TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });

  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );

  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  resetThemeStore();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
