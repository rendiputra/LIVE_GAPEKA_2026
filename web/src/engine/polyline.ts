// Polyline decoding at precision 6 (B1) plus cumulative distance, mirroring the
// Python SegmentGeom: point lookup by bisect, clamped to the polyline length.

export type LatLon = [number, number];

export function decodePolyline(encoded: string, precision = 6): LatLon[] {
  const factor = Math.pow(10, precision);
  const points: LatLon[] = [];
  let index = 0;
  let lat = 0;
  let lon = 0;

  const nextValue = (): number => {
    let result = 0;
    let shift = 0;
    let byte = 0x20;
    while (byte >= 0x20) {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    }
    return result & 1 ? ~(result >> 1) : result >> 1;
  };

  while (index < encoded.length) {
    lat += nextValue();
    lon += nextValue();
    points.push([lat / factor, lon / factor]);
  }
  return points;
}

/** Haversine, identical formula to pipeline.rail_graph.haversine_m. */
export function haversineM(a: LatLon, b: LatLon): number {
  const R = 6371008.8;
  const rad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * rad;
  const dLon = (b[1] - a[1]) * rad;
  const lat1 = a[0] * rad;
  const lat2 = b[0] * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function cumulativeM(points: LatLon[]): number[] {
  const out = [0];
  for (let i = 1; i < points.length; i += 1) {
    out.push(out[i - 1] + haversineM(points[i - 1], points[i]));
  }
  return out;
}

export interface SegmentGeometry {
  points: LatLon[];
  cumulative: number[];
  lengthM: number;
  from: string;
  to: string;
}

export function buildSegment(
  segment: { from: string; to: string; length_m: number; polyline: string },
  reversed: boolean,
): SegmentGeometry {
  const decoded = decodePolyline(segment.polyline);
  const points = reversed ? [...decoded].reverse() : decoded;
  return {
    points,
    cumulative: cumulativeM(points),
    lengthM: segment.length_m,
    from: reversed ? segment.to : segment.from,
    to: reversed ? segment.from : segment.to,
  };
}

/** Mirror of SegmentGeom.point_at: clamp on the POLYLINE length, not length_m. */
export function pointAt(geometry: SegmentGeometry, distanceM: number): LatLon {
  const { points, cumulative } = geometry;
  if (points.length === 0) throw new Error("segment has no geometry");
  if (distanceM <= 0) return points[0];
  const polylineLength = cumulative[cumulative.length - 1];
  if (distanceM >= polylineLength) return points[points.length - 1];

  // bisect_left
  let lo = 0;
  let hi = cumulative.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (cumulative[mid] < distanceM) lo = mid + 1;
    else hi = mid;
  }
  const index = lo;
  if (index <= 0) return points[0];
  if (index >= points.length) return points[points.length - 1];

  const before = cumulative[index - 1];
  const after = cumulative[index];
  const span = after - before;
  if (span <= 0) return points[index];
  const ratio = (distanceM - before) / span;
  const [lat0, lon0] = points[index - 1];
  const [lat1, lon1] = points[index];
  return [lat0 + (lat1 - lat0) * ratio, lon0 + (lon1 - lon0) * ratio];
}

/** Bearing in degrees, same atan2 form as the Python engine. */
export function bearing(a: LatLon, b: LatLon): number {
  const rad = Math.PI / 180;
  const lat1 = a[0] * rad;
  const lat2 = b[0] * rad;
  const dLon = (b[1] - a[1]) * rad;
  const x = Math.sin(dLon) * Math.cos(lat2);
  const y = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return ((Math.atan2(x, y) * 180) / Math.PI + 360) % 360;
}
