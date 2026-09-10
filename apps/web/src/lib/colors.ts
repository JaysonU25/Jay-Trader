import { useRef } from "react";

export const SERIES_SLOTS = [
  "var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
  "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)",
] as const;

export function seriesVar(slot: number): string {
  return SERIES_SLOTS[slot % SERIES_SLOTS.length];
}

/** Sequential blue ramp, light to dark. For magnitude, never identity. */
export const SEQUENTIAL = [
  "var(--seq-200)", "var(--seq-350)", "var(--seq-450)", "var(--seq-600)",
] as const;

export function sequentialVar(fraction: number): string {
  const clamped = Math.min(Math.max(fraction, 0), 1);
  const index = Math.round(clamped * (SEQUENTIAL.length - 1));
  return SEQUENTIAL[index];
}

/**
 * Assign a palette slot per id and never reassign it while the hook is mounted.
 * Removing an id frees nothing: survivors keep their color, which is the point.
 */
export function useStableColors(ids: string[]): Map<string, string> {
  const assigned = useRef(new Map<string, string>());
  const nextSlot = useRef(0);

  for (const id of ids) {
    if (!assigned.current.has(id)) {
      assigned.current.set(id, seriesVar(nextSlot.current));
      nextSlot.current += 1;
    }
  }

  return assigned.current;
}
