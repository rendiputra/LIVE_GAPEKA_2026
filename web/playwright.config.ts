import { defineConfig } from "@playwright/test";

// Tiles are stubbed, so the smoke test needs no network.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 390, height: 844 },
  },
  webServer: {
    command: "npm run build:e2e && npx vite preview --outDir dist-e2e --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
