/**
 * Scheduled ingest triggers.
 *
 * Cloudflare fires `scheduled` with the cron expression that matched, and that
 * string is the only thing distinguishing one trigger from another — so every
 * expression in wrangler.toml must be unique, even when two jobs want the same
 * cadence. See the `news` offset there.
 */

export interface Env {
  /** Origin of the API, no trailing slash. e.g. https://market-pulse.fly.dev */
  API_BASE_URL: string;
  /** Shared with the API's INGEST_HMAC_SECRET. Never logged. */
  INGEST_HMAC_SECRET: string;
}

/**
 * Cron expression to job name. Job names must match JOB_NAMES in
 * marketpulse/ingest/jobs.py; the API answers 404 for anything else.
 */
export const JOB_BY_CRON: Record<string, string> = {
  "15 13 * * *": "macro", // after the 08:30 ET FRED releases
  "30 15 * * 1-5": "fx", // after the ECB publishes, ~15:00 UTC
  "0 22 * * 1-5": "prices", // after the US close, 21:00 UTC
  "0 */6 * * *": "crypto",
  "10 */6 * * *": "news", // offset from crypto: the expression is the key
  "0 23 * * *": "earnings",
  "0 4 * * 1": "ratings", // weekly; analyst ratings barely move
};

const encoder = new TextEncoder();

function toHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * HMAC-SHA256 over `${timestamp}.${source}`, hex encoded.
 *
 * Must stay byte-identical to marketpulse.core.security.sign; the cross-language
 * vector in tests/sign.test.ts is what holds the two implementations together.
 */
export async function sign(
  secret: string,
  timestamp: string,
  source: string,
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(`${timestamp}.${source}`),
  );
  return toHex(signature);
}

export async function triggerIngest(env: Env, job: string): Promise<Response> {
  // Whole seconds: the API parses this with float() and bounds its age, so the
  // two clocks only need to agree within the replay window, not exactly.
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = await sign(env.INGEST_HMAC_SECRET, timestamp, job);

  const response = await fetch(`${env.API_BASE_URL}/internal/ingest/${job}`, {
    method: "POST",
    headers: {
      "X-Timestamp": timestamp,
      "X-Signature": signature,
      "Content-Length": "0",
    },
  });

  if (!response.ok) {
    // Body, not just status: a 401 here is almost always a secret mismatch and
    // the status alone sends you looking in the wrong place.
    const body = await response.text();
    throw new Error(
      `ingest ${job} failed: ${response.status} ${body.slice(0, 200)}`,
    );
  }
  return response;
}

export default {
  async scheduled(
    event: ScheduledController,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    const job = JOB_BY_CRON[event.cron];
    if (!job) {
      // A trigger was added to wrangler.toml without a mapping here. Loud,
      // because the symptom is otherwise a job that silently never runs.
      console.error(`no job mapped to cron expression "${event.cron}"`);
      return;
    }

    // The API answers 202 and runs the job as a background task, so this
    // resolves in well under the Worker's CPU budget.
    ctx.waitUntil(
      triggerIngest(env, job)
        .then(() => console.log(`triggered ${job}`))
        .catch((error) => console.error(String(error))),
    );
  },
};
