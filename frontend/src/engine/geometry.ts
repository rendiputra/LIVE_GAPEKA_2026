/**
 * Segment geometry helpers — the TypeScript port of the geometry half of
 * `engine/model.py` and the bearing helpers in `engine/position.py`.
 *
 * The haversine formula is copied operation-for-operation from
 * `pipeline/rail_graph.py:haversine_m` (EARTH_RADIUS_M = 6371008.8) so that
 * cumulative distances match the Python snapshot to the last bit.
 */
import type { Coordinate, SegmentGeom } from "./types";

/** Mean Earth radius used by the pipeline. Changing it breaks parity. */
export const EARTH_RADIUS_M = 6_371_008.8;

const DEG_TO_RAD = Math.PI / 180;

export function haversineM(a: Coordinate, b: Coordinate): number {
  const dLat = (b.lat - a.lat) * DEG_TO_RAD;
  const dLon = (b.lon - a.lon) * DEG_TO_RAD;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * DEG_TO_RAD) * Math.cos(b.lat * DEG_TO_RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** Cumulative distance at each vertex; the first entry is always 0. */
export function cumulativeDistances(coordinates: readonly Coordinate[]): number[] {
  if (coordinates.length === 0) return [];
  const out: number[] = [0];
  for (let index = 1; index < coordinates.length; index += 1) {
    out.push(out[index - 1]! + haversineM(coordinates[index - 1]!, coordinates[index]!));
  }
  return out;
}

/**
 * Interpolate a coordinate at `distanceM` along the segment.
 *
 * Clamps against the POLYLINE length, not the reported `lengthM`: the two can
 * differ by rounding, and clamping only on `lengthM` lets the index run past the
 * end of the array (the bug fixed in `engine/model.py`).
 */
export function pointAt(segment: SegmentGeom, distanceM: number): Coordinate {
  const coordinates = segment.coordinates;
  const cumulative = segment.cumulativeM;
  if (coordinates.length === 0 || cumulative.length === 0) {
    throw new Error(`segment ${segment.fromCode}-${segment.toCode} has no geometry`);
  }
  if (distanceM <= 0) return coordinates[0]!;

  const polylineLength = cumulative[cumulative.length - 1]!;
  if (distanceM >= polylineLength) return coordinates[coordinates.length - 1]!;

  // bisect_left: the first index whose cumulative distance is >= distanceM.
  let low = 0;
  let high = cumulative.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (cumulative[mid]! < distanceM) low = mid + 1;
    else high = mid;
  }
  const index = low;

  if (index <= 0) return coordinates[0]!;
  if (index >= coordinates.length) return coordinates[coordinates.length - 1]!;

  const before = cumulative[index - 1]!;
  const after = cumulative[index]!;
  const span = after - before;
  if (span <= 0) return coordinates[index]!;

  const ratio = (distanceM - before) / span;
  const p0 = coordinates[index - 1]!;
  const p1 = coordinates[index]!;
  return {
    lat: p0.lat + (p1.lat - p0.lat) * ratio,
    lon: p0.lon + (p1.lon - p0.lon) * ratio,
  };
}

/** Initial bearing from `a` to `b`, in degrees clockwise from north, in [0, 360). */
export function bearing(a: Coordinate, b: Coordinate): number {
  const lat1 = a.lat * DEG_TO_RAD;
  const lon1 = a.lon * DEG_TO_RAD;
  const lat2 = b.lat * DEG_TO_RAD;
  const lon2 = b.lon * DEG_TO_RAD;
  const dLon = lon2 - lon1;
  const x = Math.sin(dLon) * Math.cos(lat2);
  const y = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return ((Math.atan2(x, y) * 180) / Math.PI + 360) % 360;
}
