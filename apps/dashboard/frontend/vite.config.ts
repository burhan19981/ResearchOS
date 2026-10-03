import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Local development convenience: the backend runs on :8000, the
      // frontend dev server on :5173 — proxying /api avoids needing
      // CORS at all for `npm run dev` (the FastAPI app's CORS config
      // in main.py is a fallback for setups that don't use this proxy).
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    // Same proxy for `vite preview` (the production-build server) —
    // used by the Playwright e2e smoke test, which runs the real
    // backend on :8000 against a seeded, isolated SQLite database.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
