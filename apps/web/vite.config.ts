import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Root-relative alias: Vite resolves "/src" from the project root, so this
  // config needs no node:url import and therefore no @types/node.
  resolve: {
    alias: { "@": "/src" },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    css: false,
    env: { VITE_API_BASE: "http://127.0.0.1:8000" },
  },
});
