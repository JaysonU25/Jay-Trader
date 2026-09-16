import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "@/router";

/**
 * jsdom applies no CSS, so what is *visible* at a given width cannot be
 * asserted here — the media queries are the browser's job. What is testable,
 * and what actually matters for the drawer being usable, is the state machine
 * and its ARIA contract: a labelled toggle, an accurate aria-expanded, and the
 * three ways a drawer must be dismissible.
 */
function renderApp(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const toggle = () => screen.getByRole("button", { name: /navigation/i });

describe("collapsible navigation", () => {
  it("exposes a labelled toggle that starts collapsed", () => {
    renderApp();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("points the toggle at the nav it controls", () => {
    renderApp();
    const controlled = toggle().getAttribute("aria-controls");
    expect(controlled).toBeTruthy();
    expect(document.getElementById(controlled!)).toBe(
      screen.getByRole("navigation"),
    );
  });

  it("opens and closes on click", async () => {
    renderApp();
    await userEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when a destination is chosen", async () => {
    // Without this the drawer covers the page you just navigated to.
    renderApp();
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("link", { name: /macro/i }));

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(await screen.findByRole("heading", { name: /macro/i })).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    renderApp();
    await userEvent.click(toggle());
    await userEvent.keyboard("{Escape}");

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when the backdrop is tapped", async () => {
    renderApp();
    await userEvent.click(toggle());

    await userEvent.click(screen.getByTestId("nav-backdrop"));
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("has no backdrop while collapsed", () => {
    renderApp();
    expect(screen.queryByTestId("nav-backdrop")).not.toBeInTheDocument();
  });

  it("keeps every destination reachable regardless of drawer state", () => {
    // The links stay mounted; only CSS moves them off-canvas. A drawer that
    // unmounted its links would break in-page search and tab order on desktop.
    renderApp();
    for (const name of [/overview/i, /markets/i, /macro/i, /crypto/i, /fx/i, /news/i, /pipeline/i]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });
});
