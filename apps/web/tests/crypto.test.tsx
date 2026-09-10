import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { Crypto } from "@/views/Crypto";
import { coins } from "./msw/fixtures";
import { server } from "./msw/handlers";

const BASE = "http://127.0.0.1:8000";

function renderCrypto() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Crypto />
    </QueryClientProvider>,
  );
}

describe("Crypto view", () => {
  it("explains the empty state when no coins have been ingested", async () => {
    renderCrypto();
    expect(await screen.findByText(/no crypto data yet/i)).toBeInTheDocument();
  });

  it("renders the dominance tile and the ranked chart when data exists", async () => {
    server.use(http.get(`${BASE}/v1/crypto/top`, () => HttpResponse.json(coins)));
    renderCrypto();
    // 1.9T of a 2.4T total.
    expect(await screen.findByText("79.17%")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /market cap by coin/i })).toBeInTheDocument();
  });

  it("lists coins largest first in the table view", async () => {
    server.use(http.get(`${BASE}/v1/crypto/top`, () => HttpResponse.json(coins)));
    renderCrypto();
    await screen.findByText("79.17%");

    // The chart shows first, so the table has to be opened before it exists.
    await userEvent.click(screen.getByRole("button", { name: "Table" }));

    const rows = await screen.findAllByRole("row");
    // rows[0] is the header.
    expect(rows[1]).toHaveTextContent("Bitcoin");
    expect(rows[2]).toHaveTextContent("Ethereum");
  });
});
