/**
 * The map's data layer. These builders are pure functions of the snapshot, so
 * they are unit-testable and they build the GeoJSON ONCE, not per animation
 * frame. The only source that changes per frame is the trains collection the
 * worker returns.
 *
 * Colour semantics (Clean Transit Light — no dark mode, no art treatment):
 *   antarkota reguler (Book 1)  royal blue  #1D4ED8
 *   lokal           (Book 2)    teal        #0D9488
 *   fakultatif                  amber       #D97706
 *   selected train              rose        #E11D48
 */
import type { SegmentGeom, ServiceClass, Station, Trip } from "../engine/types";

export const COLOUR_ANTARKOTA = "#1D4ED8";
export const COLOUR_LOKAL = "#0D9488";
export const COLOUR_FAKULTATIF = "#D97706";
export const COLOUR_SELECTED = "#E11D48";
export const COLOUR_RAIL = "#6B7280";
export const COLOUR_RAIL_CASING = "#FFFFFF";

export type TrainColour =
  | typeof COLOUR_ANTARKOTA
  | typeof COLOUR_LOKAL
  | typeof COLOUR_FAKULTATIF;

export type TrainLayerName = "antarkota-reguler" | "lokal" | "fakultatif";

/** The ten hub stations shown from z6. */
export const HUB_CODES: readonly string[] = [
  "GMR",
  "PSE",
  "BD",
  "CN",
  "SMT",
  "YK",
  "SLO",
  "SGU",
  "SBI",
  "ML",
];

export const MAX_STATION_LABEL_ZOOM = 12;

/** Semantic colour for a train, by book and class. */
export function trainColour(book: number, serviceClass: ServiceClass): TrainColour {
  if (serviceClass === "fakultatif") return COLOUR_FAKULTATIF;
  return book === 2 ? COLOUR_LOKAL : COLOUR_ANTARKOTA;
}

export function trainLayerName(book: number, serviceClass: ServiceClass): TrainLayerName {
  if (serviceClass === "fakultatif") return "fakultatif";
  return book === 2 ? "lokal" : "antarkota-reguler";
}

/** `50 · Gajayana`, or the bare number when the PDF printed no name. */
export function trainLabel(trainNo: string, name: string): string {
  const trimmed = name.trim();
  if (trimmed === "" || trimmed === trainNo.trim()) return trainNo.trim();
  return `${trainNo.trim()} · ${trimmed}`;
}

export type StationLevel = "hub" | "regional";

export function stationLevel(code: string): StationLevel {
  return (HUB_CODES as readonly string[]).includes(code) ? "hub" : "regional";
}

function lineCoordinates(segment: SegmentGeom): Array<readonly [number, number]> {
  return segment.coordinates.map((point) => [point.lon, point.lat] as const);
}

export interface GeoJsonFeatureCollection {
  readonly type: "FeatureCollection";
  readonly features: readonly GeoJsonFeature[];
}

export interface GeoJsonFeature {
  readonly type: "Feature";
  readonly id?: string;
  readonly geometry:
    | { readonly type: "Point"; readonly coordinates: readonly [number, number] }
    | { readonly type: "LineString"; readonly coordinates: readonly (readonly [number, number])[] }
    | {
        readonly type: "MultiLineString";
        readonly coordinates: readonly (readonly (readonly [number, number])[])[];
      };
  readonly properties: Record<string, unknown>;
}

/**
 * The unique routed segments of the network, one per station pair.
 *
 * A trip list repeats the same pair many times (both directions, every train),
 * so `trips.flatMap(t => t.segments)` produces thousands of overlapping copies.
 * The map wants each physical segment once: 391 for Gapeka 2026.
 */
export function uniqueRailSegments(trips: readonly Trip[]): SegmentGeom[] {
  const seen = new Set<string>();
  const out: SegmentGeom[] = [];
  for (const trip of trips) {
    for (const segment of trip.segments) {
      const key =
        segment.fromCode < segment.toCode
          ? `${segment.fromCode}|${segment.toCode}`
          : `${segment.toCode}|${segment.fromCode}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(segment);
    }
  }
  return out;
}

/** One LineString per unique segment. */
export function railGeoJSON(segments: readonly SegmentGeom[]): GeoJsonFeatureCollection {
  return {
    type: "FeatureCollection",
    features: segments.map((segment) => ({
      type: "Feature",
      id: `${segment.fromCode}-${segment.toCode}`,
      geometry: { type: "LineString" as const, coordinates: lineCoordinates(segment) },
      properties: {
        fromCode: segment.fromCode,
        toCode: segment.toCode,
        quality: segment.quality,
        lengthM: segment.lengthM,
      },
    })),
  };
}

/** Convenience: the network's rail geometry as map-ready GeoJSON. */
export function railNetworkGeoJSON(trips: readonly Trip[]): GeoJsonFeatureCollection {
  return railGeoJSON(uniqueRailSegments(trips));
}

/**
 * The selected train's route: its oriented polylines as a single
 * MultiLineString, so the casing + highlight pair renders as one path.
 */
export function routeGeoJSON(
  segments: readonly SegmentGeom[],
  tripId = "selected",
): GeoJsonFeatureCollection {
  if (segments.length === 0) return { type: "FeatureCollection", features: [] };
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: tripId,
        geometry: {
          type: "MultiLineString" as const,
          coordinates: segments.map((segment) => lineCoordinates(segment)),
        },
        properties: { tripId },
      },
    ],
  };
}

/**
 * Located stations as Points. Stations without a coordinate (CIK, STM, TPR) are
 * omitted: they cannot be drawn, but they still exist in the timetable and in
 * search.
 */
export function stationFeatures(stations: Iterable<Station>): GeoJsonFeature[] {
  const features: GeoJsonFeature[] = [];
  for (const station of stations) {
    if (station.lat === null || station.lon === null) continue;
    features.push({
      type: "Feature",
      id: station.code,
      geometry: {
        type: "Point" as const,
        coordinates: [station.lon, station.lat] as const,
      },
      properties: {
        code: station.code,
        name: station.officialName,
        disambiguator: station.disambiguator,
        level: stationLevel(station.code),
        label: station.officialName,
      },
    });
  }
  return features;
}

export function stationsGeoJSON(stations: Iterable<Station>): GeoJsonFeatureCollection {
  return { type: "FeatureCollection", features: stationFeatures(stations) };
}
