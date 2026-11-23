/**
 * `TrainPosition[]` -> a GeoJSON FeatureCollection for the map.
 *
 * GeoJSON is `[lon, lat]`, which is the opposite of every other coordinate in
 * this codebase; the test pins the order so it cannot silently flip.
 */
import type { TrainPosition } from "../engine/types";

export interface PositionsFeatureProperties {
  readonly tripId: string;
  readonly trainNo: string;
  readonly name: string;
  readonly relation: string;
  readonly status: string;
  readonly bearing: number;
  readonly speedKmh: number;
  readonly sM: number;
  readonly fromCode: string;
  readonly toCode: string;
  readonly nextStopCode: string | null;
  readonly nextStopTime: string | null;
  readonly estimated: true;
  readonly coarse: boolean;
  readonly hasBypassedWaypoints: boolean;
  readonly hasStraightLineSegment: boolean;
  readonly serviceClass: string;
  readonly motionModel: string;
}

export interface PositionsFeature {
  readonly type: "Feature";
  readonly id: string;
  readonly geometry: { readonly type: "Point"; readonly coordinates: readonly [number, number] };
  readonly properties: PositionsFeatureProperties;
}

export interface PositionsFeatureCollection {
  readonly type: "FeatureCollection";
  readonly features: readonly PositionsFeature[];
}

export function toPositionsGeoJSON(
  positions: readonly TrainPosition[],
): PositionsFeatureCollection {
  return {
    type: "FeatureCollection",
    features: positions.map((position) => ({
      type: "Feature",
      id: position.tripId,
      geometry: {
        type: "Point",
        coordinates: [position.lon, position.lat] as const,
      },
      properties: {
        tripId: position.tripId,
        trainNo: position.trainNo,
        name: position.name,
        relation: position.relation,
        status: position.status,
        bearing: position.bearing,
        speedKmh: position.speedKmh,
        sM: position.sM,
        fromCode: position.fromCode,
        toCode: position.toCode,
        nextStopCode: position.nextStopCode,
        nextStopTime: position.nextStopTime,
        estimated: position.estimated,
        coarse: position.coarse,
        hasBypassedWaypoints: position.hasBypassedWaypoints,
        hasStraightLineSegment: position.hasStraightLineSegment,
        serviceClass: position.serviceClass,
        motionModel: position.motionModel,
      },
    })),
  };
}
