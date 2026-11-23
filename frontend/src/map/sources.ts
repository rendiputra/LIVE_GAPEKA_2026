/**
 * Tile layer configuration and the MapLibre layer stack.
 *
 * External endpoints are limited to the two map providers of ADR 010. Fonts,
 * icons and the MapLibre JS are self-hosted; these URLs are the only network
 * dependency the map has, and a failure to load them is reported in the UI
 * rather than left as a grey canvas.
 */
import {
  COLOUR_RAIL,
  COLOUR_RAIL_CASING,
  COLOUR_SELECTED,
  MAX_STATION_LABEL_ZOOM,
} from "./layers";

export type BasemapId = "positron" | "liberty";
export type OverlayId = "default" | "infrastruktur" | "maxspeed";

export interface BasemapOption {
  readonly id: BasemapId;
  readonly label: string;
  readonly style: string;
}

export function basemapUrl(id: BasemapId): string {
  return `https://tiles.openfreemap.org/styles/${id}`;
}

export const BASEMAPS: {
  readonly default: BasemapId;
  readonly options: readonly BasemapOption[];
} = {
  default: "positron",
  options: [
    { id: "positron", label: "Clean", style: basemapUrl("positron") },
    { id: "liberty", label: "Detail", style: basemapUrl("liberty") },
  ],
};

export interface OverlayOption {
  readonly id: OverlayId;
  readonly label: string;
  readonly credit: string;
}

export const OVERLAYS: {
  readonly default: OverlayId;
  readonly options: readonly OverlayOption[];
} = {
  default: "default",
  options: [
    { id: "default", label: "Default", credit: "" },
    {
      id: "infrastruktur",
      label: "Infrastruktur",
      credit: "OpenRailwayMap (OSM)",
    },
    { id: "maxspeed", label: "Max Speed", credit: "OpenRailwayMap (OSM)" },
  ],
};

/**
 * Raster tile URLs. OpenRailwayMap serves 512x512 PNGs for a 256 tile, so
 * MapLibre must be told the tile size is 256 and let it pick the scale.
 */
export function overlayTiles(id: OverlayId): string | null {
  switch (id) {
    case "default":
      return null;
    case "infrastruktur":
      return "https://tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png";
    case "maxspeed":
      return "https://tiles.openrailwaymap.org/maxspeed/{z}/{x}/{y}.png";
    default:
      throw new Error(`unknown overlay: ${String(id)}`);
  }
}

export interface RasterSource {
  readonly type: "raster";
  readonly tiles: readonly string[];
  readonly tileSize: number;
  readonly attribution: string;
}

const OVERLAY_ATTRIBUTION =
  'Data © OpenStreetMap contributors, Style <a href="https://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA 2.0</a> <a href="https://openrailwaymap.org/">OpenRailwayMap</a>';

export function buildTileSource(id: OverlayId): RasterSource | null {
  const tiles = overlayTiles(id);
  if (tiles === null) return null;
  return {
    type: "raster",
    tiles: [tiles],
    tileSize: 256,
    attribution: OVERLAY_ATTRIBUTION,
  };
}

/**
 * The layers this app adds, bottom to top. They are appended after the basemap's
 * own layers, so every one of them draws over the basemap. Order is load-bearing:
 *
 *   rail casing, rail, route casing, route, overlay (raster), stations, trains
 */
export interface MapLayerSpec {
  readonly id: string;
  readonly type: "line" | "circle" | "symbol" | "raster";
  readonly source: string;
  readonly minzoom?: number;
  readonly maxzoom?: number;
  readonly filter?: unknown;
  readonly layout?: Record<string, unknown>;
  readonly paint?: Record<string, unknown>;
}

export function styleLayers(): MapLayerSpec[] {
  return [
    {
      id: "gapeka-rail-casing",
      type: "line",
      source: "gapeka-rail",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": COLOUR_RAIL_CASING, "line-width": 4.5, "line-opacity": 0.9 },
    },
    {
      id: "gapeka-rail",
      type: "line",
      source: "gapeka-rail",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": COLOUR_RAIL, "line-width": 2.2, "line-opacity": 0.85 },
    },
    {
      id: "gapeka-route-casing",
      type: "line",
      source: "gapeka-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": COLOUR_RAIL_CASING, "line-width": 8 },
    },
    {
      id: "gapeka-route-line",
      type: "line",
      source: "gapeka-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": COLOUR_SELECTED, "line-width": 5 },
    },
    {
      id: "gapeka-overlay",
      type: "raster",
      source: "gapeka-overlay",
      paint: { "raster-opacity": 0.9 },
    },
    {
      id: "gapeka-station-hubs",
      type: "circle",
      source: "gapeka-stations",
      minzoom: 6,
      maxzoom: 9,
      filter: ["==", ["get", "level"], "hub"],
      paint: {
        "circle-radius": 4,
        "circle-color": "#111827",
        "circle-stroke-color": "#FFFFFF",
        "circle-stroke-width": 1.5,
      },
    },
    {
      id: "gapeka-station-regionals",
      type: "circle",
      source: "gapeka-stations",
      minzoom: 9,
      maxzoom: MAX_STATION_LABEL_ZOOM + 4,
      filter: ["==", ["get", "level"], "regional"],
      paint: {
        "circle-radius": 3,
        "circle-color": "#374151",
        "circle-stroke-color": "#FFFFFF",
        "circle-stroke-width": 1.2,
      },
    },
    {
      // z6-8: hubs only.
      id: "gapeka-station-hub-labels",
      type: "symbol",
      source: "gapeka-stations",
      minzoom: 6,
      maxzoom: 9,
      filter: ["==", ["get", "level"], "hub"],
      layout: {
        "text-field": [
          "case",
          ["has", "disambiguator"],
          ["concat", ["get", "name"], " · ", ["get", "code"]],
          ["coalesce", ["get", "label"], ["get", "name"]],
        ],
        "text-font": ["Noto Sans Regular"],
        "text-size": 10,
        "text-anchor": "left",
        "text-offset": [0.7, 0],
        "text-allow-overlap": false,
        "text-optional": true,
        "text-padding": 2,
      },
      paint: {
        "text-color": "#1F2937",
        "text-halo-color": "#FFFFFF",
        "text-halo-width": 1.5,
        "text-halo-blur": 0.5,
      },
    },
    {
      // z9-11: regional stations appear.
      id: "gapeka-station-regional-labels",
      type: "symbol",
      source: "gapeka-stations",
      minzoom: 9,
      maxzoom: MAX_STATION_LABEL_ZOOM,
      filter: ["==", ["get", "level"], "regional"],
      layout: {
        "text-field": [
          "case",
          ["has", "disambiguator"],
          ["concat", ["get", "name"], " · ", ["get", "code"]],
          ["coalesce", ["get", "label"], ["get", "name"]],
        ],
        "text-font": ["Noto Sans Regular"],
        "text-size": 11,
        "text-anchor": "left",
        "text-offset": [0.7, 0],
        "text-allow-overlap": false,
        "text-optional": true,
        "text-padding": 2,
      },
      paint: {
        "text-color": "#1F2937",
        "text-halo-color": "#FFFFFF",
        "text-halo-width": 1.5,
        "text-halo-blur": 0.5,
      },
    },
    {
      // z12+: every station, with its code.
      id: "gapeka-station-labels",
      type: "symbol",
      source: "gapeka-stations",
      minzoom: 12,
      layout: {
        "text-field": ["concat", ["get", "name"], " · ", ["get", "code"]],
        "text-font": ["Noto Sans Regular"],
        "text-size": 12,
        "text-anchor": "left",
        "text-offset": [0.7, 0],
        "text-allow-overlap": false,
        "text-optional": true,
        "text-padding": 2,
      },
      paint: {
        "text-color": "#1F2937",
        "text-halo-color": "#FFFFFF",
        "text-halo-width": 1.5,
        "text-halo-blur": 0.5,
      },
    },
    {
      // The marker's own colour: one feature per active trip, no clipping.
      id: "gapeka-trains",
      type: "circle",
      source: "gapeka-trains",
      paint: {
        "circle-radius": 6,
        "circle-color": ["coalesce", ["get", "colour"], "#2563EB"],
        "circle-stroke-color": "#FFFFFF",
        "circle-stroke-width": 2,
        "circle-stroke-opacity": 0.95,
      },
    },
    {
      // The name sits BELOW the marker so it never hides the dot it labels.
      id: "gapeka-trains-label",
      type: "symbol",
      source: "gapeka-trains",
      layout: {
        "text-field": ["coalesce", ["get", "label"], ["get", "trainNo"]],
        "text-font": ["Noto Sans Bold"],
        "text-size": ["interpolate", ["linear"], ["zoom"], 6, 10, 9, 11, 12, 11, 14, 12],
        "text-anchor": "top",
        "text-offset": [0, 0.9],
        "text-allow-overlap": false,
        "text-ignore-placement": false,
        "text-optional": true,
        "text-priority": 1_000,
        "icon-priority": 1_000,
        "text-padding": 4,
        "text-letter-spacing": 0.01,
      },
      paint: {
        "text-color": "#111827",
        "text-halo-color": "#FFFFFF",
        "text-halo-width": 2,
        "text-halo-blur": 0.5,
        "text-opacity": 0.95,
      },
    },
    {
      id: "gapeka-selected-halo",
      type: "circle",
      source: "gapeka-selected",
      paint: {
        "circle-radius": 16,
        "circle-color": "rgba(0,0,0,0)",
        "circle-stroke-color": COLOUR_SELECTED,
        "circle-stroke-width": 3,
        "circle-stroke-opacity": 0.95,
      },
    },
  ];
}
