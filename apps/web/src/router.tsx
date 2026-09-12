import { useRoutes, type RouteObject } from "react-router";

import { Layout } from "@/components/Layout";
import { Crypto } from "@/views/Crypto";
import { Fx } from "@/views/Fx";
import { Macro } from "@/views/Macro";
import { Markets } from "@/views/Markets";
import { NewsEarnings } from "@/views/NewsEarnings";
import { Overview } from "@/views/Overview";
import { Pipeline } from "@/views/Pipeline";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Overview /> },
      { path: "markets", element: <Markets /> },
      { path: "macro", element: <Macro /> },
      { path: "crypto", element: <Crypto /> },
      { path: "fx", element: <Fx /> },
      { path: "news", element: <NewsEarnings /> },
      { path: "pipeline", element: <Pipeline /> },
      { path: "*", element: <p>Page not found</p> },
    ],
  },
];

/**
 * Declarative routing rather than createBrowserRouter. The data router builds a
 * Request for every navigation using the environment's AbortSignal, which Node's
 * undici Request rejects under jsdom. No route here has a loader or an action,
 * so the data router offers nothing in exchange for that breakage.
 */
export function AppRoutes() {
  return useRoutes(routes);
}
