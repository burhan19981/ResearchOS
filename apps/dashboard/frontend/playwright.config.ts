import { defineConfig, devices } from "@playwright/test";

/**
 * A single end-to-end smoke test exercising the real FastAPI backend
 * (against an isolated SQLite database, seeded via a setup script) and
 * the real built frontend together — the one scenario the spec asks
 * for: select project -> overview -> pipeline -> experiment/run ->
 * approval center -> back to overview. See docs/PHASE_DASHBOARD_V1.md's
 * Testing section for how to run this locally.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4300",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "npm run e2e:api",
      port: 8000,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run preview -- --port 4300 --strictPort",
      port: 4300,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
