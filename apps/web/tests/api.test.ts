import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError, apiGet } from "@/lib/api";
import { server } from "./msw/handlers";

const BASE = "http://127.0.0.1:8000";

describe("apiGet", () => {
  it("returns the parsed body on 200", async () => {
    const result = await apiGet<{ status: string }>("/v1/health");
    expect(result).toEqual({ status: "ok" });
  });

  it("throws ApiError carrying the status and the detail field", async () => {
    server.use(
      http.get(`${BASE}/v1/prices/NOPE`, () =>
        HttpResponse.json({ detail: "prices for NOPE not found" }, { status: 404 }),
      ),
    );
    await expect(apiGet("/v1/prices/NOPE")).rejects.toMatchObject({
      status: 404,
      detail: "prices for NOPE not found",
    });
    await expect(apiGet("/v1/prices/NOPE")).rejects.toBeInstanceOf(ApiError);
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    server.use(
      http.get(`${BASE}/v1/status`, () => new HttpResponse("gateway blew up", { status: 502 })),
    );
    await expect(apiGet("/v1/status")).rejects.toMatchObject({ status: 502 });
  });

  it("appends only the query params that are defined", async () => {
    let seen = "";
    server.use(
      http.get(`${BASE}/v1/news`, ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json([]);
      }),
    );
    await apiGet("/v1/news", { symbol: "AAPL", limit: undefined });
    expect(seen).toBe("?symbol=AAPL");
  });
});
