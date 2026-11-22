// Build-time guard (T5): a production build must not use the public OSM server.
import { defineConfig } from "vite";

import { assertProductionTiles, normaliseTileMode } from "./src/tilePolicy";

export default defineConfig(({ command, mode }) => {
  if (command === "build") {
    // `vite build` defaults to production; `--mode development` opts out.
    assertProductionTiles(normaliseTileMode(process.env.VITE_TILE_MODE), mode !== "development");
  }

  return {
    base: "./",
    build: { target: "es2022", sourcemap: false },
    test: {
      environment: "node",
      include: ["tests/**/*.test.ts"],
    },
  };
});
