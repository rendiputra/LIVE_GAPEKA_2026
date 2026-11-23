/**
 * Google polyline decoding, scaled to `precision` decimal places.
 *
 * Mirrors `pipeline/export_web.py:encode_polyline`: coordinates are integers at
 * `10**precision`, delta-encoded, zig-zag transformed, then split into 5-bit
 * chunks biased by 63. Anything that does not terminate cleanly is an error —
 * a silently truncated polyline would place a train in the wrong place.
 */

export interface Point {
  readonly lat: number;
  readonly lon: number;
}

export class PolylineError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PolylineError";
  }
}

export function decodePolyline(encoded: string, precision = 6): Point[] {
  if (encoded.length === 0) return [];
  const factor = 10 ** precision;
  const points: Point[] = [];

  let index = 0;
  let lat = 0;
  let lon = 0;

  const nextValue = (): number => {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      if (index >= encoded.length) {
        throw new PolylineError("truncated polyline: chunk sequence ended mid-value");
      }
      byte = encoded.charCodeAt(index++) - 63;
      if (byte < 0 || byte > 0x3f) {
        throw new PolylineError(`invalid polyline character at index ${index - 1}`);
      }
      result |= (byte & 0x1f) << shift;
      shift += 5;
      if (shift > 60) {
        throw new PolylineError("polyline value exceeds the safe integer range");
      }
    } while (byte >= 0x20);

    // zig-zag: the low bit is the sign
    return result & 1 ? ~(result >> 1) : result >> 1;
  };

  while (index < encoded.length) {
    lat += nextValue();
    lon += nextValue();
    points.push({ lat: lat / factor, lon: lon / factor });
  }

  return points;
}
