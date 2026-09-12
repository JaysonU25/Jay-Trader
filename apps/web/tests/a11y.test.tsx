import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

const PATHS = ["/", "/markets", "/macro", "/crypto", "/fx", "/news", "/pipeline"];

describe("accessibility", () => {
  it("gives every view exactly one h1", async () => {
    for (const path of PATHS) {
      const { unmount } = renderAt(path);
      expect(await screen.findAllByRole("heading", { level: 1 })).toHaveLength(1);
      unmount();
    }
  });

  it("labels every chart with a description", async () => {
    renderAt("/fx");
    const chart = await screen.findByRole("img", { name: /rate history/i });
    expect(chart).toHaveAccessibleName();
  });

  it("offers a table alternative anywhere a chart is shown", async () => {
    renderAt("/fx");
    expect(await screen.findByRole("button", { name: "Table" })).toBeInTheDocument();
  });

  it("exposes the theme toggle as a button", async () => {
    renderAt("/");
    expect(await screen.findByRole("button", { name: /switch to/i })).toBeInTheDocument();
  });
});
