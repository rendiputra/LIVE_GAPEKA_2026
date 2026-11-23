import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright is installed and configured now so that `make frontend-e2e` has a
 * target; the specs arrive with the map in Turn 3. There is deliberately no
 * spec in `e2e/` yet — a smoke test of a placeholder page proves nothing.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm exec vite preview --outDir dist --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});