// T5: the tile-source guard. A production build must never ship the public OSM
// tile server, because its usage policy forbids this traffic.

import { describe, expect, it } from "vitest";

import { assertProductionTiles, normaliseTileMode } from "../src/tilePolicy";

describe("tile policy", () => {
  it("defaults to self-hosted pmtiles", () => {
    expect(normaliseTileMode(undefined)).toBe("pmtiles");
    expect(normaliseTileMode("")).toBe("pmtiles");
    expect(normaliseTileMode("pmtiles")).toBe("pmtiles");
  });

  it("accepts osm only when asked explicitly", () => {
    expect(normaliseTileMode("osm")).toBe("osm");
  });

  it("ignores an unknown value rather than guessing", () => {
    expect(normaliseTileMode("mapbox")).toBe("pmtiles");
  });

  it("throws for a production build on public OSM tiles", () => {
    expect(() => assertProductionTiles("osm", true)).toThrow(/Refusing/);
  });

  it("allows the OSM dev server outside production", () => {
    expect(() => assertProductionTiles("osm", false)).not.toThrow();
  });

  it("allows pmtiles in production", () => {
    expect(() => assertProductionTiles("pmtiles", true)).not.toThrow();
  });
});
