export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type QueryParams = Record<string, string | number | undefined | null>;

const BASE = import.meta.env.VITE_API_BASE ?? "";

function buildUrl(path: string, params?: QueryParams): string {
  const url = new URL(path, BASE || window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

export async function apiGet<T>(path: string, params?: QueryParams): Promise<T> {
  const response = await fetch(buildUrl(path, params), {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    // The API's error body is {"detail": "..."} but a proxy or gateway can
    // answer with HTML or plain text; never let the parse failure mask the status.
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the status-text fallback */
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}
