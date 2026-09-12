import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
export type ThemeChoice = Theme | "system";

const KEY = "market-pulse-theme";

// A module-level store rather than per-component state: useTheme is called from
// the toggle, the nav, and every Chart, and they must all see one value without
// threading a provider through the tree.
const listeners = new Set<() => void>();

function read(): ThemeChoice {
  const stored = localStorage.getItem(KEY);
  return stored === "light" || stored === "dark" ? stored : "system";
}

let choice: ThemeChoice = "system";
let hydrated = false;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): ThemeChoice {
  if (!hydrated) {
    choice = read();
    hydrated = true;
  }
  return choice;
}

function stamp(next: ThemeChoice): void {
  const root = document.documentElement;
  if (next === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", next);
}

export function setThemeChoice(next: ThemeChoice): void {
  if (next === "system") localStorage.removeItem(KEY);
  else localStorage.setItem(KEY, next);
  choice = next;
  hydrated = true;
  stamp(next);
  for (const listener of listeners) listener();
}

/** Tests clear localStorage between cases; drop the cached value with it. */
export function resetThemeStore(): void {
  choice = "system";
  hydrated = false;
  for (const listener of listeners) listener();
}

function resolve(value: ThemeChoice): Theme {
  if (value !== "system") return value;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const current = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const setTheme = useCallback((next: ThemeChoice) => setThemeChoice(next), []);
  return { theme: resolve(current), choice: current, setTheme };
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" onClick={() => setTheme(next)}>
      Switch to {next}
    </button>
  );
}
