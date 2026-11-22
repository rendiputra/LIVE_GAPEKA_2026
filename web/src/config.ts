// Tile source configuration (T5). ONE setting decides the basemap.
//
// "pmtiles"  self-hosted Protomaps vector tiles (web/public/tiles/java.pmtiles)
// "osm"      public OpenStreetMap raster tiles, DEVELOPMENT ONLY
//
// A production build refuses to use the public OSM server: its usage policy
// forbids this traffic, so shipping it would be a policy violation, not a bug.

import { normaliseTileMode } from "./tilePolicy";

export type { TileMode } from "./tilePolicy";

export const TILE_MODE = normaliseTileMode(
  import.meta.env.VITE_TILE_MODE as string | undefined,
);

export const OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const PMTILES_URL = "pmtiles://tiles/java.pmtiles";
export const GLYPHS_URL = "tiles/assets/fonts/{fontstack}/{range}.pbf";
export const SPRITE_URL = "tiles/assets/sprites/light";
export const OSM_ATTRIBUTION = "© OpenStreetMap contributors";
