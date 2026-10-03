import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    // The Playwright e2e spec under e2e/ uses @playwright/test's own
    // test()/expect() API, incompatible with Vitest's — keep the two
    // runners' suites strictly separate.
    exclude: ["node_modules/**", "e2e/**"],
  },
});
