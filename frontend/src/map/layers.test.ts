/**
 * The map's data layer: turning the snapshot into the GeoJSON that MapLibre
 * renders in WebGL. Everything is built ONCE per snapshot (or on selection),
 * never per frame — the only thing that updates per frame is the trains
 * FeatureCollection, which comes straight out of the worker.
 *
 * Colour semantics (Clean Transit Light):
 *   antarkota reguler (Book 1)  -> royal blue  #1D4ED8
 *   lokal          (Book 2)     -> teal        #0D9488
 *   fakultatif                  -> amber       #D97706
 *   selected train              -> rose        #E11D48
 */
import { describe, expect, it } from "vitest";
import {
  HUB_CODES,
  MAX_STATION_LABEL_ZOOM,
  railGeoJSON,
  routeGeoJSON,
  stationFeatures,
  stationLevel,
  trainColour,
  trainLayerName,
  trainLabel,
} from "./layers";

describe("trainColour", () => {
  it("colours Book 1 antarkota reguler royal blue", () => {
    expect(trainColour(1, "reguler")).toBe("#1D4ED8");
  });

  it("colours Book 2 lokal teal", () => {
    expect(trainColour(2, "reguler")).toBe("#0D9488");
  });

  it("colours fakultatif amber regardless of book", () => {
    expect(trainColour(1, "fakultatif")).toBe("#D97706");
    expect(trainColour(2, "fakultatif")).toBe("#D97706");
  });

  it("covers an unknown service class", () => {
    expect(trainColour(1, "unknown")).toBeDefined();
  });

  it("returns the semantic colour for a book", () => {
    expect(trainLayerName(1, "reguler")).toBe("antarkota-reguler");
    expect(trainLayerName(2, "reguler")).toBe("lokal");
    expect(trainLayerName(1, "fakultatif")).toBe("fakultatif");
  });
});

describe("trainLabel", () => {
  it("shows the number then the name", () => {
    expect(trainLabel("50", "Gajayana")).toBe("50 · Gajayana");
  });

  it("shows the number alone when the PDF printed no name", () => {
    expect(trainLabel("151", "")).toBe("151");
  });

  it("never repeats the number as the name", () => {
    expect(trainLabel("50", "50")).toBe("50");
  });
});

describe("stationLevel", () => {
  it("treats the ten hubs as major", () => {
    for (const hub of HUB_CODES) {
      expect(stationLevel(hub)).toBe("hub");
    }
    expect(HUB_CODES).toEqual(
      expect.arrayContaining(["GMR", "PSE", "BD", "CN", "SMT", "YK", "SLO", "SGU", "SBI", "ML"]),
    );
  });

  it("treats any other located station as regional", () => {
    expect(stationLevel("PWT")).toBe("regional");
    expect(stationLevel("PK")).toBe("regional");
  });

  it("uses the code alone as the display label", () => {
    expect(stationLevel("GMR")).toBe("hub");
  });

  it("keeps the zoom thresholds stable", () => {
    // z6-8 hubs, z9-11 regional, z12+ everything: 12 is the ceiling.
    expect(MAX_STATION_LABEL_ZOOM).toBe(12);
  });
});

describe("stationFeatures", () => {
  const stations = [
    { code: "GMR", officialName: "Gambir", disambiguator: null, lat: -6.176716, lon: 106.830508 },
    { code: "PK", officialName: "Pekalongan", disambiguator: null, lat: -6.888, lon: 109.676 },
    // No coordinate: must be excluded silently (it is not on the map).
    { code: "CIK", officialName: "Cikampek", disambiguator: null, lat: null, lon: null },
  ];

  it("skips stations without a coordinate", () => {
    const features = stationFeatures(stations);
    expect(features.map((feature) => feature.properties.code)).toEqual(["GMR", "PK"]);
  });

  it("orders coordinates as [lon, lat]", () => {
    const [gambir] = stationFeatures(stations);
    expect(gambir!.geometry.coordinates).toEqual([106.830508, -6.176716]);
  });

  it("marks hubs so the layer can filter by zoom band", () => {
    const [gambir, second] = stationFeatures(stations);
    expect(gambir!.properties.level).toBe("hub");
    expect(second!.properties.level).toBe("regional");
  });

  it("carries the display name for the label", () => {
    const [gambir] = stationFeatures(stations);
    expect(gambir!.properties.name).toBe("Gambir");
  });
});

describe("railGeoJSON", () => {
  it("emits one MultiLineString feature per segment", () => {
    const collection = railGeoJSON([
      {
        coordinates: [
          { lat: -6.2, lon: 106.8 },
          { lat: -6.21, lon: 106.8 },
        ],
      },
      {
        coordinates: [
          { lat: -6.21, lon: 106.8 },
          { lat: -6.22, lon: 106.9 },
        ],
      },
    ] as never);
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.features).toHaveLength(2);
    expect(collection.features[0]!.geometry.type).toBe("LineString");
    expect(collection.features[0]!.geometry.coordinates).toEqual([
      [106.8, -6.2],
      [106.8, -6.21],
    ]);
  });
});

describe("routeGeoJSON", () => {
  it("emits the trip's oriented polylines as one feature", () => {
    const collection = routeGeoJSON([
      { coordinates: [{ lat: -6.2, lon: 106.8 }, { lat: -6.21, lon: 106.8 }] },
      { coordinates: [{ lat: -6.21, lon: 106.8 }, { lat: -6.22, lon: 106.9 }] },
    ] as never);
    const [feature] = collection.features;
    expect(feature!.geometry.type).toBe("MultiLineString");
    expect(feature!.geometry.coordinates).toHaveLength(2);
  });

  it("emits an empty collection for a trip without geometry", () => {
    expect(routeGeoJSON([] as never)).toEqual({ type: "FeatureCollection", features: [] });
  });
});
