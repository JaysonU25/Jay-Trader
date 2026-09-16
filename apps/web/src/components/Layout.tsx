import { useEffect, useState } from "react";
import { Outlet } from "react-router";

import { Nav } from "./Nav";

const NAV_ID = "primary-nav";

export function Layout() {
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  return (
    <div className={`app${navOpen ? " app--nav-open" : ""}`}>
      {/* Visible only under the mobile breakpoint; on desktop the nav is
          always on screen and this bar would be redundant chrome. */}
      <header className="topbar">
        <button
          type="button"
          className="topbar__toggle"
          aria-expanded={navOpen}
          aria-controls={NAV_ID}
          onClick={() => setNavOpen((open) => !open)}
        >
          <span aria-hidden="true">☰</span> Navigation
        </button>
        <strong>Jay Trader</strong>
      </header>

      {/* The nav stays mounted at every width: only CSS moves it off-canvas.
          Unmounting it would drop its links out of tab order and in-page
          search on desktop, where the drawer does not apply at all. */}
      <Nav id={NAV_ID} onNavigate={() => setNavOpen(false)} />

      {navOpen ? (
        <div
          className="nav-backdrop"
          data-testid="nav-backdrop"
          // Tapping outside is the gesture people expect from a drawer; the
          // Escape handler above covers the keyboard, and the toggle itself
          // stays reachable, so this does not need its own ARIA role.
          onClick={() => setNavOpen(false)}
        />
      ) : null}

      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
