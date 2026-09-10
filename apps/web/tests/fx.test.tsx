import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { Fx } from "@/views/Fx";
import { server } from "./msw/handlers";

function renderFx() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Fx />
    </QueryClientProvider>,
  );
}

describe("FX view", () => {
  it("shows the converted result and the rate date", async () => {
    renderFx();
    expect(await screen.findByText(/15,624.68/)).toBeInTheDocument();
    expect(screen.getByText(/Sep 4, 2026/)).toBeInTheDocument();
  });

  it("sends the amount the user types to the API", async () => {
    let seen = "";
    server.use(
      http.get("http://127.0.0.1:8000/v1/fx/convert", ({ request }) => {
        seen = new URL(request.url).searchParams.get("amount") ?? "";
        return HttpResponse.json({
          from_currency: "USD",
          to_currency: "JPY",
          amount: 250,
          rate: 156.2468,
          result: 39061.7,
          rate_date: "2026-09-04",
        });
      }),
    );
    renderFx();
    const amount = await screen.findByLabelText(/amount/i);
    await userEvent.clear(amount);
    await userEvent.type(amount, "250");
    expect(await screen.findByText(/39,061.70/)).toBeInTheDocument();
    expect(seen).toBe("250");
  });

  it("reports a 404 for an unknown currency rather than showing a stale result", async () => {
    server.use(
      http.get("http://127.0.0.1:8000/v1/fx/convert", () =>
        HttpResponse.json({ detail: "currency ZZZ not found" }, { status: 404 }),
      ),
    );
    renderFx();
    expect(await screen.findByRole("alert")).toHaveTextContent(/ZZZ not found/);
  });
});
