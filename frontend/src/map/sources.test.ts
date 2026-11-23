/**
 * The tile layer configuration. URLs are the ONLY external endpoints this app
 * talks to (ADR 010): OpenFreeMap for the vector basemap and OpenRailwayMap for
 * raster overlays. Everything else is self-hosted.
 *
 * OpenRailwayMap serves 512x512 PNGs at a 256 tile size (double resolution), so
 * the raster source declares `tileSize: 256` and serves `512` on retina via
 * `tilePixelRatio: 2` — MapLibre derives that from device pixel ratio.
 */
import { describe, expect, it } from "vitest";
import {
  BASEMAPS,
  OVERLAYS,
  basemapUrl,
  buildTileSource,
  overlayTiles,
  styleLayers,
} from "./sources";

describe("basemaps", () => {
  it("defaults to positron (Clean)", () => {
    expect(BASEMAPS.default).toBe("positron");
    expect(basemapUrl("positron")).toBe("https://tiles.openfreemap.org/styles/positron");
  });

  it("offers liberty as the selectable alternative", () => {
    expect(basemapUrl("liberty")).toBe("https://tiles.openfreemap.org/styles/liberty");
    expect(BASEMAPS.options.map((basemap) => basemap.id)).toEqual(["positron", "liberty"]);
  });

  it("gives each style a human label", () => {
    expect(BASEMAPS.options[0]!.label).toBe("Clean");
    expect(BASEMAPS.options[1]!.label).toBe("Detail");
  });
});

describe("overlays", () => {
  it("offers exactly the two OpenRailwayMap styles, plus none", () => {
    expect(OVERLAYS.options.map((overlay) => overlay.id)).toEqual([
      "default",
      "infrastruktur",
      "maxspeed",
    ]);
  });

  it("defaults to no overlay", () => {
    expect(OVERLAYS.default).toBe("default");
  });

  it("points at the tiles.openrailwaymap.org host, not the www site", () => {
    // `www.openrailwaymap.org/standard/...` is the map page, not tiles: it 404s.
    expect(overlayTiles("infrastruktur")).toBe(
      "https://tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png",
    );
    expect(overlayTiles("maxspeed")).toBe(
      "https://tiles.openrailwaymap.org/maxspeed/{z}/{x}/{y}.png",
    );
  });

  it("returns no tiles for the default overlay", () => {
    expect(overlayTiles("default")).toBeNull();
  });

  it("describes the tiles as 512x512 served at 256", () => {
    const source = buildTileSource("infrastruktur");
    expect(source).not.toBeNull();
    expect(source!.tiles).toEqual(["https://tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png"]);
    expect(source!.tileSize).toBe(256);
  });

  it("never invents a tile URL for an unknown overlay", () => {
    expect(() => overlayTiles("bogus" as never)).toThrow();
  });
});

describe("styleLayers", () => {
  const layers = styleLayers();

  it("has unique layer ids", () => {
    const ids = layers.map((layer) => layer.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("keeps the rail casing below the rail line", () => {
    const ids = layers.map((layer) => layer.id);
    expect(ids.indexOf("gapeka-rail-casing")).toBeLessThan(ids.indexOf("gapeka-rail"));
  });

  it("puts the selected route above the network rail", () => {
    const ids = layers.map((layer) => layer.id);
    expect(ids.indexOf("gapeka-route-casing")).toBeGreaterThan(ids.indexOf("gapeka-rail"));
    expect(ids.indexOf("gapeka-route-line")).toBeGreaterThan(ids.indexOf("gapeka-route-casing"));
  });

  it("keeps station symbols below the trains", () => {
    const ids = layers.map((layer) => layer.id);
    expect(ids.indexOf("gapeka-station-labels")).toBeLessThan(ids.indexOf("gapeka-trains-label"));
  });

  it("gives train labels the highest priority", () => {
    const layer = layers.find((entry) => entry.id === "gapeka-trains-label")!;
    // Train labels are added LAST so they are topmost and win placement over
    // stations. symbol-sort-key keeps the selected train first on collision.
    expect(layer.layout?.["symbol-sort-key"]).toBeDefined();
    expect(layer.layout?.["text-ignore-placement"]).toBe(false);
  });

  it("never lets station labels overlap", () => {
    for (const id of [
      "gapeka-station-hub-labels",
      "gapeka-station-regional-labels",
      "gapeka-station-labels",
    ]) {
      const layer = layers.find((entry) => entry.id === id)!;
      expect(layer.layout?.["text-allow-overlap"]).toBe(false);
      expect(layer.layout?.["text-optional"]).toBe(true);
    }
  });

  it("does not let stations steal placement from train labels", () => {
    // Train labels win by layer order (they are last/topmost), NOT by
    // text-ignore-placement: true, which would let other labels draw on top.
    const trainLayer = layers.find((entry) => entry.id === "gapeka-trains-label")!;
    expect(trainLayer.layout?.["text-ignore-placement"]).toBe(false);
    expect(trainLayer.layout?.["text-allow-overlap"]).toBe(false);
    const station = layers.find((entry) => entry.id === "gapeka-station-hub-labels")!;
    expect(station.layout?.["text-ignore-placement"]).toBe(true);
  });

  it("gates hubs to z6-8 and regionals to z9+", () => {
    const hubFilter = layers.find((entry) => entry.id === "gapeka-station-hubs")!.filter;
    expect(JSON.stringify(hubFilter)).toContain("hub");
    const regionalFilter = layers.find((entry) => entry.id === "gapeka-station-regionals")!.filter;
    expect(JSON.stringify(regionalFilter)).toContain("regional");
    expect(layers.find((entry) => entry.id === "gapeka-station-hubs")!.minzoom).toBe(6);
    expect(layers.find((entry) => entry.id === "gapeka-station-regionals")!.minzoom).toBe(9);
  });

  it("shows the train name, falling back to the number alone", () => {
    const layer = layers.find((entry) => entry.id === "gapeka-trains-label")!;
    const field = layer.layout?.["text-field"];
    expect(JSON.stringify(field)).toContain("label");
    expect(JSON.stringify(field)).toContain("trainNo");
  });

  it("colours trains by the semantic colour property", () => {
    const layer = layers.find((entry) => entry.id === "gapeka-trains")!;
    expect(JSON.stringify(layer.paint)).toContain("colour");
  });

  it("splits the station labels into three zoom bands (hubs, regional, all)", () => {
    const ids = layers.map((layer) => layer.id);
    expect(ids).toContain("gapeka-station-hub-labels");
    expect(ids).toContain("gapeka-station-regional-labels");
    const hubLabels = layers.find((entry) => entry.id === "gapeka-station-hub-labels")!;
    const regionalLabels = layers.find(
      (entry) => entry.id === "gapeka-station-regional-labels",
    )!;
    expect(hubLabels.minzoom).toBe(6);
    expect(hubLabels.maxzoom).toBe(9);
    expect(regionalLabels.minzoom).toBe(9);
    expect(JSON.stringify(hubLabels.filter)).toContain("hub");
    expect(JSON.stringify(regionalLabels.filter)).toContain("regional");
  });

  it("labels trains below the marker so the dot stays visible", () => {
    const layer = layers.find((entry) => entry.id === "gapeka-trains-label")!;
    expect(layer.layout?.["text-anchor"]).toBe("top");
    expect(layer.layout?.["text-field"]).toBeDefined();
  });
});