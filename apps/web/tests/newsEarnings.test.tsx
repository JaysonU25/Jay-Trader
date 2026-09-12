import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NewsEarnings } from "@/views/NewsEarnings";

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NewsEarnings />
    </QueryClientProvider>,
  );
}

describe("News & Earnings view", () => {
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
});
