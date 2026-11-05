import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against an already running stack (docker compose up) seeded with
 * `python -m aigentix.cli seed-dev`. Configure with E2E_BASE_URL and E2E_PASSWORD.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
