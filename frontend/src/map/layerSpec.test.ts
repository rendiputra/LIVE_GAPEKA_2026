/**
 * Layer-spec hygiene.
 *
 * Bug 1 shipped a symbol layer with `text-priority` / `icon-priority`. Those
 * names do not exist in MapLibre's style spec, so `map.addLayer` rejected the
 * whole layer and train labels never rendered — a failure that was invisible
 * because the addLayer error used to be swallowed.
 *
 * This test catches that class of bug at build time, with no browser and no
 * debug global: every layout/paint key we emit must be one MapLibre accepts,
 * and layer ids must be unique.
 */
import { describe, expect, it } from "vitest";
import { styleLayers } from "./sources";

/** Layout keys MapLibre accepts, per layer type (only what we may emit). */
const SYMBOL_LAYOUT = new Set([
  "visibility",
  "symbol-placement",
  "symbol-spacing",
  "symbol-avoid-edges",
  "symbol-sort-key",
  "symbol-z-order",
  "text-allow-overlap",
  "text-anchor",
  "text-field",
  "text-font",
  "text-ignore-placement",
  "text-justify",
  "text-keep-upright",
  "text-letter-spacing",
  "text-line-height",
  "text-max-angle",
  "text-max-width",
  "text-offset",
  "text-optional",
  "text-padding",
  "text-radial-offset",
  "text-rotate",
  "text-size",
  "text-transform",
  "text-variable-anchor",
  "text-writing-mode",
  "icon-allow-overlap",
  "icon-anchor",
  "icon-ignore-placement",
  "icon-image",
  "icon-keep-upright",
  "icon-offset",
  "icon-optional",
  "icon-padding",
  "icon-pitch-alignment",
  "icon-rotate",
  "icon-rotation-alignment",
  "icon-size",
  "icon-text-fit",
  "icon-text-fit-padding",
]);

const LINE_LAYOUT = new Set(["visibility", "line-cap", "line-join", "line-miter-limit", "line-round-limit"]);
const CIRCLE_LAYOUT = new Set(["visibility", "circle-sort-key"]);
const RASTER_LAYOUT = new Set(["visibility"]);

const SYMBOL_PAINT = new Set([
  "icon-opacity",
  "icon-color",
  "icon-halo-color",
  "icon-halo-width",
  "icon-halo-blur",
  "icon-translate",
  "text-opacity",
  "text-color",
  "text-halo-color",
  "text-halo-width",
  "text-halo-blur",
  "text-translate",
]);

const LINE_PAINT = new Set([
  "line-opacity",
  "line-color",
  "line-translate",
  "line-width",
  "line-gap-width",
  "line-offset",
  "line-blur",
  "line-dasharray",
  "line-pattern",
]);

const CIRCLE_PAINT = new Set([
  "circle-radius",
  "circle-color",
  "circle-blur",
  "circle-opacity",
  "circle-stroke-width",
  "circle-stroke-color",
  "circle-stroke-opacity",
  "circle-pitch-scale",
  "circle-pitch-alignment",
  "circle-translate",
]);

const RASTER_PAINT = new Set([
  "raster-opacity",
  "raster-hue-rotate",
  "raster-brightness-min",
  "raster-brightness-max",
  "raster-saturation",
  "raster-contrast",
  "raster-fade-duration",
]);

const ALLOWED = {
  symbol: { layout: SYMBOL_LAYOUT, paint: SYMBOL_PAINT },
  line: { layout: LINE_LAYOUT, paint: LINE_PAINT },
  circle: { layout: CIRCLE_LAYOUT, paint: CIRCLE_PAINT },
  raster: { layout: RASTER_LAYOUT, paint: RASTER_PAINT },
} as const;

describe("layer specs are valid MapLibre style fragments", () => {
  const layers = styleLayers();

  it("has unique layer ids", () => {
    const ids = layers.map((layer) => layer.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("emits no layout key MapLibre would reject", () => {
    const offenders: string[] = [];
    for (const layer of layers) {
      const allowed = ALLOWED[layer.type].layout;
      for (const key of Object.keys(layer.layout ?? {})) {
        if (!allowed.has(key)) offenders.push(`${layer.id}.layout.${key}`);
      }
    }
    expect(offenders, offenders.join(", ")).toEqual([]);
  });

  it("emits no paint key MapLibre would reject", () => {
    const offenders: string[] = [];
    for (const layer of layers) {
      const allowed = ALLOWED[layer.type].paint;
      for (const key of Object.keys(layer.paint ?? {})) {
        if (!allowed.has(key)) offenders.push(`${layer.id}.paint.${key}`);
      }
    }
    expect(offenders, offenders.join(", ")).toEqual([]);
  });

  it("does not use the removed priority properties", () => {
    // The exact Bug 1 regression.
    const json = JSON.stringify(layers);
    expect(json).not.toContain("text-priority");
    expect(json).not.toContain("icon-priority");
  });

  it("only asks for glyph fonts OpenFreeMap actually hosts", () => {
    const hosted = new Set(["Noto Sans Regular", "Noto Sans Bold", "Noto Sans Italic"]);
    const requested = new Set<string>();
    for (const layer of layers) {
      const fonts = layer.layout?.["text-font"];
      if (Array.isArray(fonts)) for (const font of fonts) requested.add(String(font));
    }
    expect(requested.size).toBeGreaterThan(0);
    for (const font of requested) expect(hosted.has(font), font).toBe(true);
  });

  it("keeps every source reference resolvable to a declared source id", () => {
    const declared = new Set([
      "gapeka-rail",
      "gapeka-route",
      "gapeka-stations",
      "gapeka-trains",
      "gapeka-selected",
      "gapeka-overlay",
    ]);
    for (const layer of layers) {
      expect(declared.has(layer.source), `${layer.id} -> ${layer.source}`).toBe(true);
    }
  });

  it("places the train label layer last so it wins placement", () => {
    const ids = layers.map((layer) => layer.id);
    expect(ids.at(-1)).toBe("gapeka-selected-halo");
    expect(ids.at(-2)).toBe("gapeka-trains-label");
  });
});