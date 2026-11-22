// Pure tile policy so both the Vite config (Node) and the app (browser) can use
// it. This module must not touch `import.meta.env`.

export type TileMode = "pmtiles" | "osm";

export function normaliseTileMode(raw: string | undefined): TileMode {
  return raw === "osm" ? "osm" : "pmtiles";
}

/** Throws in a production build when the public OSM server would be used. */
export function assertProductionTiles(mode: TileMode, isProduction: boolean): void {
  if (isProduction && mode === "osm") {
    throw new Error(
      "Refusing to build for production with the public OSM tile server. " +
        "Set VITE_TILE_MODE=pmtiles and run `make basemap`, or choose a provider " +
        "you are allowed to use (see docs/DEPLOY.md).",
    );
  }
}
