import { defineConfig } from "vite";

// Static site: no server, no API. `npm run build` emits web/dist/.
export default defineConfig({
  base: "./",
  build: { target: "es2022", sourcemap: false },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
} as never);
