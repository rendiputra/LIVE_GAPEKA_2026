import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // The parity gate is a single 6,000-frame comparison; give it room without
    // hiding a real hang (the engine is pure, so this is generous, not tight).
    testTimeout: 120_000,
  },
});
