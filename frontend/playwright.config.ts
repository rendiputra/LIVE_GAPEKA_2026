import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright is installed and configured now so that `make frontend-e2e` has a
 * target; the specs arrive with the map in Turn 3. There is deliberately no
 * spec in `e2e/` yet — a smoke test of a placeholder page proves nothing.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // Four headless Chromium instances each rendering a WebGL map under
  // SwiftShader contend for one CPU, which starves a click mid-action. Two
  // workers keep the map responsive without making the suite slow.
  workers: process.env.CI ? 2 : 2,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  timeout: 90_000,
  projects: [
    {
      // Turn 3b requires an explicit 1280x800 desktop viewport, not the
      // device preset's default.
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
      // The acceptance suite also runs on mobile (its own project below).
      testIgnore: /acceptance\.spec\.ts/,
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
      testMatch: /acceptance\.spec\.ts/,
    },
    {
      // The acceptance suite at the desktop viewport, named explicitly so the
      // report can point at both required viewports.
      name: "desktop-acceptance",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
      testMatch: /acceptance\.spec\.ts/,
    },
  ],
  webServer: [
    {
      command: "pnpm exec vite preview --outDir dist --port 4173 --strictPort --host 127.0.0.1",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // Sub-path deployment: `base: "./"` must work from /sub/ too.
      command: "node e2e/subpath-server.mjs dist /sub/ 4175",
      url: "http://127.0.0.1:4175/sub/",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});