import { formatPercent } from "@/lib/format";

import { Sparkline } from "./Sparkline";

export function StatTile({
  label,
  value,
  delta,
  points,
}: {
  label: string;
  value: string;
  delta?: number | null;
  points?: number[];
}) {
  // Direction is carried by the arrow glyph and the signed number, not by hue
  // alone — the color only reinforces what the text already says.
  const direction =
    delta === null || delta === undefined || delta === 0 ? null : delta > 0 ? "up" : "down";
  const deltaColor =
    direction === "up"
      ? "var(--status-good)"
      : direction === "down"
        ? "var(--status-critical)"
        : "var(--text-muted)";
  const glyph = direction === "up" ? "▲" : direction === "down" ? "▼" : "•";

  return (
    <div className="card">
      <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 24, marginTop: 4 }}>{value}</div>
      {delta !== undefined ? (
        <div style={{ color: deltaColor, fontSize: 12, marginTop: 2 }}>
          {`${glyph} ${formatPercent(delta)}`}
        </div>
      ) : null}
      {points && points.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Sparkline points={points} label={label} />
        </div>
      ) : null}
    </div>
  );
}
