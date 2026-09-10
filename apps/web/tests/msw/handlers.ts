import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import * as fx from "./fixtures";

const BASE = "http://127.0.0.1:8000";

export const handlers = [
  http.get(`${BASE}/v1/health`, () => HttpResponse.json({ status: "ok" })),
  http.get(`${BASE}/v1/dashboard`, () => HttpResponse.json(fx.dashboard)),
  http.get(`${BASE}/v1/assets`, () => HttpResponse.json([])),
  http.get(`${BASE}/v1/prices/:symbol`, () => HttpResponse.json(fx.bars)),
  http.get(`${BASE}/v1/series`, ({ request }) => {
    const category = new URL(request.url).searchParams.get("category");
    if (category === "fx") return HttpResponse.json(fx.fxSeries);
    if (category) return HttpResponse.json(fx.macroSeries.filter((s) => s.category === category));
    return HttpResponse.json([...fx.fxSeries, ...fx.macroSeries]);
  }),
  http.get(`${BASE}/v1/series/:source/*`, () => HttpResponse.json(fx.observations)),
  http.get(`${BASE}/v1/crypto/top`, () => HttpResponse.json([])),
  http.get(`${BASE}/v1/fx/convert`, () =>
    HttpResponse.json({
      from_currency: "USD", to_currency: "JPY", amount: 100,
      rate: 156.2468, result: 15624.68, rate_date: "2026-09-04",
    }),
  ),
  http.get(`${BASE}/v1/news`, () => HttpResponse.json(fx.news)),
  http.get(`${BASE}/v1/earnings/upcoming`, () => HttpResponse.json(fx.earnings)),
  http.get(`${BASE}/v1/ratings/:symbol`, () => HttpResponse.json(fx.ratings)),
  http.get(`${BASE}/v1/status`, () => HttpResponse.json(fx.runs)),
];

export const server = setupServer(...handlers);
