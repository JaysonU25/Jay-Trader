import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { Markets } from "@/views/Markets";
import { bars } from "./msw/fixtures";
import { server } from "./msw/handlers";

const BASE = "http://127.0.0.1:8000";

function renderMarkets() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Markets />
    </QueryClientProvider>,
  );
}

describe("Markets view", () => {
  it("explains the empty state when no assets have been ingested", async () => {
    renderMarkets();
    expect(await screen.findByText(/no equities ingested yet/i)).toBeInTheDocument();
  });

  it("lists assets and charts the first one when data exists", async () => {
    server.use(
      http.get(`${BASE}/v1/assets`, () =>
        HttpResponse.json([
          { symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE", sector: null },
          { symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", sector: "Technology" },
        ]),
      ),
      http.get(`${BASE}/v1/prices/:symbol`, () => HttpResponse.json(bars)),
    );
    renderMarkets();
    expect(await screen.findByRole("option", { name: /SPDR S&P 500 ETF/ })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /SPY close/i })).toBeInTheDocument();
  });

  it("notes that prices are unadjusted for splits", async () => {
    server.use(
      http.get(`${BASE}/v1/assets`, () =>
        HttpResponse.json([
          { symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE", sector: null },
        ]),
      ),
    );
    renderMarkets();
    expect(await screen.findByText(/unadjusted for splits/i)).toBeInTheDocument();
  });
});
