import { defineConfig } from "@playwright/test";

// Tiles are stubbed, so the smoke test needs no network.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // One worker: `vite preview` is single-threaded and every test loads the full
  // schedule, so parallel workers starve each other and time out non-deterministically.
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 390, height: 844 },
  },
  webServer: [
    {
      command:
        "npm run build:e2e && npx vite preview --outDir dist-e2e --port 4173 --strictPort --host 127.0.0.1",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: true,
      timeout: 180_000,
    },
    {
      command: "node e2e/subpath-server.mjs dist-e2e /sub/ 4174",
      url: "http://127.0.0.1:4174/sub/",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
