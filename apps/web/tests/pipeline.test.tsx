import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Pipeline } from "@/views/Pipeline";

function renderPipeline() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Pipeline />
    </QueryClientProvider>,
  );
}

describe("Pipeline view", () => {
  it("labels each status in text, never by color alone", async () => {
    renderPipeline();
    expect(await screen.findByText("partial")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("shows the row counts and call counts for each run", async () => {
    renderPipeline();
    expect(await screen.findByText("89,819")).toBeInTheDocument();
  });

  it("surfaces the stored error text for a failed run", async () => {
    renderPipeline();
    expect(await screen.findByText(/outputsize=full is a premium feature/i)).toBeInTheDocument();
  });
});
