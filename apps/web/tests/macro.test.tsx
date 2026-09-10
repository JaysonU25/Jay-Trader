import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { Macro } from "@/views/Macro";
import { server } from "./msw/handlers";

function renderMacro() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Macro />
    </QueryClientProvider>,
  );
}

describe("Macro view", () => {
  it("lists every macro series as a selectable checkbox", async () => {
    renderMacro();
    expect(
      await screen.findByRole("checkbox", { name: /consumer price index/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /unemployment rate/i })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /10-year treasury/i })).toBeInTheDocument();
  });

  it("selects the first series by default so the view is never blank", async () => {
    renderMacro();
    expect(await screen.findByRole("checkbox", { name: /consumer price index/i })).toBeChecked();
  });

  it("renders the observation table with formatted values and an em dash for nulls", async () => {
    renderMacro();
    await userEvent.click(await screen.findByRole("button", { name: "Table" }));
    expect(await screen.findByRole("cell", { name: "100.00" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument();
  });

  it("shows an empty state when no series are selected", async () => {
    renderMacro();
    await userEvent.click(await screen.findByRole("checkbox", { name: /consumer price index/i }));
    expect(await screen.findByText(/select at least one series/i)).toBeInTheDocument();
  });

  it("surfaces an API failure instead of rendering an empty chart", async () => {
    server.use(
      http.get("http://127.0.0.1:8000/v1/series", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderMacro();
    expect(await screen.findByRole("alert")).toHaveTextContent(/500/);
  });
});
