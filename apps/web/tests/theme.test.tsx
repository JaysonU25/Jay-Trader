import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { resetThemeStore, ThemeToggle, useTheme } from "@/lib/theme";

function Probe() {
  const { theme } = useTheme();
  return <span data-testid="theme">{theme}</span>;
}

describe("theme", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    localStorage.clear();
    resetThemeStore();
  });

  it("defaults to light when the OS reports no dark preference", () => {
    render(<Probe />);
    expect(screen.getByTestId("theme")).toHaveTextContent("light");
  });

  it("stamps data-theme on the root when toggled", async () => {
    render(
      <>
        <ThemeToggle />
        <Probe />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: /dark/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("persists the choice across mounts", async () => {
    const { unmount } = render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: /dark/i }));
    unmount();
    render(<Probe />);
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });
});
