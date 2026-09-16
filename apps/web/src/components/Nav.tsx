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

export function Nav({
  id,
  onNavigate,
}: {
  id?: string;
  /** Called after a destination is chosen, so the drawer can close itself. */
  onNavigate?: () => void;
}) {
  return (
    <nav id={id} className="nav" aria-label="Primary">
      <strong className="nav__brand">Jay Trader</strong>
      {LINKS.map(([to, label]) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) => (isActive ? "nav__link nav__link--active" : "nav__link")}
          onClick={onNavigate}
        >
          {label}
        </NavLink>
      ))}
      <div className="nav__footer">
        <ThemeToggle />
      </div>
    </nav>
  );
}
