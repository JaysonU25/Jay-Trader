import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { NewsEarnings } from "@/views/NewsEarnings";
import { news as newsFixture } from "./msw/fixtures";
import { server } from "./msw/handlers";

const BASE = "http://127.0.0.1:8000";

const ASSETS = [
  { symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", sector: "Technology" },
  { symbol: "MSFT", name: "Microsoft Corp.", exchange: "NASDAQ", sector: "Technology" },
  { symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE", sector: null },
];

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NewsEarnings />
    </QueryClientProvider>,
  );
}

/** Serve the asset universe, and filter news by the symbol query param. */
function serveUniverse() {
  server.use(
    http.get(`${BASE}/v1/assets`, () => HttpResponse.json(ASSETS)),
    http.get(`${BASE}/v1/news`, ({ request }) => {
      const symbol = new URL(request.url).searchParams.get("symbol");
      if (!symbol) return HttpResponse.json(newsFixture);
      return HttpResponse.json(
        newsFixture.filter((item) => item.symbol === symbol.toUpperCase()),
      );
    }),
  );
}

describe("News & Earnings view", () => {
  beforeEach(serveUniverse);

  it("renders each headline as an external link", async () => {
    renderView();
    const link = await screen.findByRole("link", { name: /apple ships something/i });
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("shows the source and published time for each item", async () => {
    renderView();
    expect(await screen.findByText(/Reuters/)).toBeInTheDocument();
  });

  it("lists upcoming earnings with the reporting-hour label spelled out", async () => {
    renderView();
    expect(await screen.findByText(/after market close/i)).toBeInTheDocument();
  });

  it("offers every asset in the universe as a filter option", async () => {
    renderView();
    const select = await screen.findByLabelText(/symbol/i);
    // Options arrive with useAssets, so wait for the universe to land.
    await screen.findByRole("option", { name: "AAPL" });

    // The default has to exist, or there is no way back to the unfiltered feed.
    expect(screen.getByRole("option", { name: /all symbols/i })).toBeInTheDocument();
    for (const asset of ASSETS) {
      expect(screen.getByRole("option", { name: asset.symbol })).toBeInTheDocument();
    }
    expect(select).toHaveValue("");
  });

  it("shows every symbol's news before a filter is chosen", async () => {
    renderView();
    expect(await screen.findByRole("link", { name: /apple ships something/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /microsoft does a thing/i })).toBeInTheDocument();
  });

  it("sends the chosen symbol to the API and narrows the feed", async () => {
    let requested: string | null = "never-set";
    server.use(
      http.get(`${BASE}/v1/news`, ({ request }) => {
        requested = new URL(request.url).searchParams.get("symbol");
        return HttpResponse.json(
          requested
            ? newsFixture.filter((n) => n.symbol === requested!.toUpperCase())
            : newsFixture,
        );
      }),
    );

    renderView();
    await screen.findByRole("link", { name: /apple ships something/i });

    await userEvent.selectOptions(await screen.findByLabelText(/symbol/i), "MSFT");

    await waitFor(() => expect(requested).toBe("MSFT"));
    expect(
      await screen.findByRole("link", { name: /microsoft does a thing/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /apple ships something/i }),
    ).not.toBeInTheDocument();
  });

  it("returns to the full feed when the filter is cleared", async () => {
    renderView();
    const select = await screen.findByLabelText(/symbol/i);
    await screen.findByRole("option", { name: "MSFT" });

    await userEvent.selectOptions(select, "MSFT");
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: /apple ships something/i })).not.toBeInTheDocument(),
    );

    await userEvent.selectOptions(select, "");

    expect(
      await screen.findByRole("link", { name: /apple ships something/i }),
    ).toBeInTheDocument();
  });

  it("explains an empty feed instead of rendering a blank panel", async () => {
    renderView();
    const select = await screen.findByLabelText(/symbol/i);
    await screen.findByRole("option", { name: "SPY" });

    // SPY is in the universe but has no news in the fixture.
    await userEvent.selectOptions(select, "SPY");

    expect(await screen.findByText(/no news for SPY/i)).toBeInTheDocument();
  });

  it("still renders the feed when the asset list fails to load", async () => {
    // The dropdown is a convenience; losing it must not take the news with it.
    server.use(
      http.get(`${BASE}/v1/assets`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderView();
    expect(
      await screen.findByRole("link", { name: /apple ships something/i }),
    ).toBeInTheDocument();
  });
});
