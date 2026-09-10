import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "@/router";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("navigation", () => {
  it("renders the Overview heading at the root path", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { name: /overview/i })).toBeInTheDocument();
  });

  it("exposes a link for every view", () => {
    renderAt("/");
    for (const name of [/overview/i, /markets/i, /macro/i, /crypto/i, /fx/i, /news/i, /pipeline/i]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("navigates to Macro when its link is clicked", async () => {
    renderAt("/");
    await userEvent.click(screen.getByRole("link", { name: /macro/i }));
    expect(await screen.findByRole("heading", { name: /macro/i })).toBeInTheDocument();
  });

  it("renders a not-found message for an unknown path", async () => {
    renderAt("/nope");
    expect(await screen.findByText(/page not found/i)).toBeInTheDocument();
  });
});
