/**
 * Replace `var(--token)` strings anywhere in an ECharts option with their
 * computed values.
 *
 * ECharts draws to a canvas, and canvas colors are literal strings assigned to
 * `strokeStyle` / `fillStyle`. CSS custom properties mean nothing there: an
 * unparseable color leaves the context's previous value in place, which is how
 * every series ended up black regardless of theme. The option builders stay
 * written against tokens — that is what keeps light and dark one stylesheet —
 * and resolution happens here, once, on the way to the renderer.
 */

const VAR_PATTERN = /^var\(\s*(--[\w-]+)\s*(?:,\s*([\s\S]*?)\s*)?\)$/;

export type ReadToken = (name: string) => string;

/** Resolve one string if it is a `var(...)` reference; otherwise return it. */
export function resolveToken(value: string, read: ReadToken): string {
  const match = VAR_PATTERN.exec(value.trim());
  if (!match) return value;

  const [, name, fallback] = match;
  const resolved = read(name).trim();
  if (resolved) return resolved;

  // A declared fallback may itself be a var(), e.g. var(--a, var(--b)).
  if (fallback !== undefined) return resolveToken(fallback, read);

  // Nothing to resolve to. Returning the original var() would paint black;
  // "currentColor" at least inherits something sensible from the container.
  return "currentColor";
}

/**
 * Deep-copy `value`, resolving every `var(...)` string found along the way.
 *
 * Copies rather than mutating: ECharts options are built inside `useMemo`, and
 * rewriting them in place would leave resolved colors from the previous theme
 * baked into the memoised object.
 */
export function resolveCssVars<T>(value: T, read: ReadToken): T {
  if (typeof value === "string") {
    return resolveToken(value, read) as unknown as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => resolveCssVars(item, read)) as unknown as T;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      out[key] = resolveCssVars(item, read);
    }
    return out as T;
  }
  return value;
}

/** Reads custom properties off the document root. */
export function documentTokenReader(): ReadToken {
  const styles = getComputedStyle(document.documentElement);
  return (name) => styles.getPropertyValue(name);
}
