import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { Overview } from "@/views/Overview";
import { dashboard } from "./msw/fixtures";
import { server } from "./msw/handlers";

function renderOverview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Overview />
    </QueryClientProvider>,
  );
}

describe("Overview view", () => {
  it("renders a tile per macro sparkline", async () => {
    renderOverview();
    expect(await screen.findByText("10-Year Treasury")).toBeInTheDocument();
    expect(screen.getByText("Unemployment Rate")).toBeInTheDocument();
  });

  it("shows the signed change with a direction glyph, not color alone", async () => {
    renderOverview();
    expect(await screen.findByText(/▼ -1.40%/)).toBeInTheDocument();
  });

  it("notes which sections are empty rather than rendering a blank panel", async () => {
    renderOverview();
    expect(await screen.findByText(/no equity data/i)).toBeInTheDocument();
    expect(screen.getByText(/no crypto data/i)).toBeInTheDocument();
  });

  it("renders the pipeline summary", async () => {
    renderOverview();
    expect(await screen.findByText("partial")).toBeInTheDocument();
  });

  it("surfaces a dashboard failure as an alert", async () => {
    server.use(
      http.get("http://127.0.0.1:8000/v1/dashboard", () =>
        HttpResponse.json({ detail: "dashboard exploded" }, { status: 500 }),
      ),
    );
    renderOverview();
    expect(await screen.findByRole("alert")).toHaveTextContent(/dashboard exploded/);
  });

  it("renders every section when all data is present", async () => {
    server.use(
      http.get("http://127.0.0.1:8000/v1/dashboard", () =>
        HttpResponse.json({
          ...dashboard,
          markets: [{ label: "SPY", latest: 511, change_pct: 1.6, points: [503, 511] }],
        }),
      ),
    );
    renderOverview();
    expect(await screen.findByText("SPY")).toBeInTheDocument();
  });
});
