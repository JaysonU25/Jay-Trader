export interface Column {
  key: string;
  header: string;
  align?: "left" | "right";
}

export function DataTable({
  columns,
  rows,
  caption,
}: {
  columns: Column[];
  rows: Array<Record<string, string | number | null>>;
  caption: string;
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <caption
          style={{
            captionSide: "top",
            textAlign: "left",
            color: "var(--text-muted)",
            paddingBottom: 8,
          }}
        >
          {caption}
        </caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={{
                  textAlign: c.align ?? "left",
                  borderBottom: "1px solid var(--border)",
                  padding: "6px 8px",
                  color: "var(--text-secondary)",
                  fontWeight: 600,
                }}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td
                  key={c.key}
                  style={{
                    textAlign: c.align ?? "left",
                    borderBottom: "1px solid var(--border)",
                    padding: "6px 8px",
                    fontVariantNumeric: c.align === "right" ? "tabular-nums" : undefined,
                  }}
                >
                  {row[c.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
