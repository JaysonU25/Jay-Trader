import { NavLink } from "react-router";

import { ThemeToggle } from "@/lib/theme";

const LINKS: Array<[string, string]> = [
  ["/", "Overview"],
  ["/markets", "Markets"],
  ["/macro", "Macro"],
  ["/crypto", "Crypto"],
  ["/fx", "FX"],
  ["/news", "News & Earnings"],
  ["/pipeline", "Pipeline"],
];

export function Nav() {
  return (
    <nav
      style={{
        borderRight: "1px solid var(--border)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <strong style={{ marginBottom: 12 }}>Market Pulse</strong>
      {LINKS.map(([to, label]) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          style={({ isActive }) => ({
            color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
            fontWeight: isActive ? 600 : 400,
            textDecoration: "none",
            padding: "6px 8px",
            borderRadius: 6,
            background: isActive ? "var(--surface-1)" : "transparent",
          })}
        >
          {label}
        </NavLink>
      ))}
      <div style={{ marginTop: "auto", paddingTop: 16 }}>
        <ThemeToggle />
      </div>
    </nav>
  );
}
