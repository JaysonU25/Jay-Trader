import type { IngestStatus } from "@/lib/types";

// Status colors are reserved — they never stand in for a series hue, and they
// never carry meaning alone. The glyph is decorative; the text is the label.
const COLOR: Record<IngestStatus, string> = {
  success: "var(--status-good)",
  partial: "var(--status-warning)",
  running: "var(--text-muted)",
  failed: "var(--status-critical)",
};

const GLYPH: Record<IngestStatus, string> = {
  success: "●",
  partial: "◐",
  running: "○",
  failed: "✕",
};

export function StatusBadge({ status }: { status: IngestStatus }) {
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <span aria-hidden="true" style={{ color: COLOR[status] }}>
        {GLYPH[status]}
      </span>
      <span>{status}</span>
    </span>
  );
}
