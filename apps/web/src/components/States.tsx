import { ApiError } from "@/lib/api";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p role="status" style={{ color: "var(--text-muted)" }}>
      {label}…
    </p>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? `${error.status} — ${error.detail}`
      : error instanceof Error
        ? error.message
        : "Unknown error";
  return (
    <div role="alert" className="card" style={{ borderColor: "var(--status-critical)" }}>
      <strong style={{ color: "var(--status-critical)" }}>Request failed</strong>
      <p style={{ color: "var(--text-secondary)", margin: "8px 0 0" }}>{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} style={{ marginTop: 12 }}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card" style={{ color: "var(--text-secondary)" }}>
      <strong style={{ color: "var(--text-primary)" }}>{title}</strong>
      {hint ? <p style={{ margin: "8px 0 0" }}>{hint}</p> : null}
    </div>
  );
}
