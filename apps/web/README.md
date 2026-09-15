# Jay Trader web

React SPA over the Jay Trader API. Static build, no SSR.

## Setup

```bash
npm install
echo "VITE_API_BASE=http://127.0.0.1:8000" > .env.local
npm run dev
```

The API must be running separately — see [`../api/README.md`](../api/README.md).

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Vite dev server on :5173 |
| `npm run build` | Typecheck and build to `dist/` |
| `npm run preview` | Serve the built bundle |
| `npm test` | Vitest, MSW-backed, no network |

## Views

Overview · Markets · Macro · Crypto · FX · News & Earnings · Pipeline

Markets and Crypto render empty states until their ingest jobs succeed; both
name the vendor breakage responsible. See `docs/FOLLOWUPS.md`.

## Charts

All charts go through `src/charts/Chart.tsx`. The option builders are written
against the CSS custom properties in `src/styles/tokens.css`, so light and dark
are two separately validated palettes rather than an inversion of one.

**ECharts does not resolve those tokens** — `src/charts/resolveTokens.ts` does,
on the way to the renderer. The canvas renderer assigns colors straight to
`strokeStyle` / `fillStyle`, where `var(--series-1)` is not a valid color; the
context keeps its previous value and every series draws black. Resolution is
re-run whenever the theme changes, because the same token then reads a
different value. `tests/chart.test.tsx` asserts no `var(` ever reaches
`setOption`.

The rules the option builders enforce come from the dataviz skill and are
covered by `tests/chartOptions.test.ts`:

- One y-axis, never two. Series with different units are indexed to 100.
- Palette slots follow the entity, not its rank — removing a series never
  repaints the survivors (`useStableColors`).
- Legend at two or more series; none at one, where the title names it.
- Direct end labels at four or fewer series, dropped past that.
- Nulls stay gaps; `connectNulls` is off.
- Every chart has a table toggle. This is required relief, not a nicety: three
  light-mode palette slots fall below 3:1 contrast on the chart surface.

## Notable implementation choices

**Declarative routing, not `createBrowserRouter`.** The data router builds a
`Request` per navigation using the environment's `AbortSignal`, which Node's
undici `Request` rejects under jsdom:

```
TypeError: RequestInit: Expected signal ("AbortSignal {}") to be an instance of AbortSignal
```

No route has a loader or an action, so the data router offered nothing in
exchange for that breakage.

**Theme is a module-level store** read through `useSyncExternalStore`. The
toggle, the nav, and every chart call `useTheme`, and they must observe one
value without threading a provider through the tree.

**ECharts is stubbed in tests.** jsdom has no canvas 2D context. The logic
worth testing lives in the pure option builders, which are tested directly.

**ECharts is a separate bundle chunk** — it is roughly two thirds of the
JavaScript, and only the chart views need it.
