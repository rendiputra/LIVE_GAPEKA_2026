import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // Relative asset URLs so the bundle can be served from a sub-path (e.g.
  // https://host/gapeka/) without a rebuild. `import.meta.env.BASE_URL` becomes
  // "./", which the data fetch already normalises.
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  worker: {
    format: "es",
  },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      // MapLibre is 1.1 MB on its own. Keeping it in its own chunk means the
      // app shell can paint before WebGL is ready, and the engine/worker code
      // (which Vite already splits out) never touches the main thread bundle.
      output: {
        manualChunks: {
          maplibre: ["maplibre-gl"],
        },
      },
    },
    chunkSizeWarningLimit: 1200,
  },
});
