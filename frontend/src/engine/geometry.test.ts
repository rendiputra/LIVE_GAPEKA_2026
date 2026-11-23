/**
 * Segment geometry: cumulative distances, point lookup and bearing.
 *
 * Must match `engine/model.py:SegmentGeom.point_at` (bisect_left) and
 * `engine/position.py:_bearing_at` (a 25 m forward step, falling back to the
 * first two vertices when the step does not move).
 *
 * Reference values are from `pipeline/rail_graph.py:haversine_m`
 * (EARTH_RADIUS_M = 6371008.8) and the Python `_bearing`.
 */
import { describe, expect, it } from "vitest";
import { bearing, cumulativeDistances, haversineM, pointAt } from "./geometry";
import { segmentGeom } from "./testUtils";

describe("haversineM", () => {
  it("is zero for identical points", () => {
    expect(haversineM({ lat: 0, lon: 0 }, { lat: 0, lon: 0 })).toBe(0);
  });

  it("matches the Python reference distance", () => {
    expect(haversineM({ lat: -6.1767, lon: 106.8305 }, { lat: -6.2, lon: 106.85 })).toBeCloseTo(
      3370.3692869890947,
      6,
    );
    expect(haversineM({ lat: -6.2, lon: 106.8 }, { lat: -6.201, lon: 106.8015 })).toBeCloseTo(
      199.6486561825947,
      6,
    );
  });
});

describe("cumulativeDistances", () => {
  it("starts at zero and accumulates haversine steps", () => {
    const cumulative = cumulativeDistances([
      { lat: -6.2, lon: 106.8 },
      { lat: -6.201, lon: 106.8015 },
      { lat: -6.2025, lon: 106.803 },
    ]);
    expect(cumulative[0]).toBe(0);
    expect(cumulative[1]).toBeCloseTo(199.6486561825947, 6);
    expect(cumulative[2]).toBeGreaterThan(cumulative[1]!);
  });

  it("is empty for an empty line and single-valued for one point", () => {
    expect(cumulativeDistances([])).toEqual([]);
    expect(cumulativeDistances([{ lat: 1, lon: 2 }])).toEqual([0]);
  });
});

describe("pointAt", () => {
  // A straight north-south line with a known vertex at 100 m and 250 m.
  const line = segmentGeom({
    fromCode: "AAA",
    toCode: "BBB",
    lengthM: 250,
    coordinates: [
      { lat: -6.2, lon: 106.8 },
      { lat: -6.201, lon: 106.8015 },
      { lat: -6.2025, lon: 106.803 },
    ],
  });

  it("returns the first point at or below zero distance", () => {
    expect(pointAt(line, -5)).toEqual({ lat: -6.2, lon: 106.8 });
    expect(pointAt(line, 0)).toEqual({ lat: -6.2, lon: 106.8 });
  });

  it("interpolates linearly between vertices", () => {
    const half = pointAt(line, line.cumulativeM[1]! / 2);
    expect(half.lat).toBeCloseTo((-6.2 + -6.201) / 2, 9);
    expect(half.lon).toBeCloseTo((106.8 + 106.8015) / 2, 9);
  });

  it("returns the exact vertex at a cumulative boundary", () => {
    const atVertex = pointAt(line, line.cumulativeM[1]!);
    expect(atVertex.lat).toBeCloseTo(-6.201, 9);
    expect(atVertex.lon).toBeCloseTo(106.8015, 9);
  });

  it("clamps against the polyline length, not the reported length_m", () => {
    // A reported length longer than the polyline must not run off the array.
    const optimistic = segmentGeom({
      fromCode: "AAA",
      toCode: "BBB",
      lengthM: 10_000,
      coordinates: [
        { lat: -6.2, lon: 106.8 },
        { lat: -6.201, lon: 106.8015 },
      ],
    });
    expect(pointAt(optimistic, 9_000)).toEqual({ lat: -6.201, lon: 106.8015 });
    expect(pointAt(optimistic, optimistic.cumulativeM.at(-1)!)).toEqual({
      lat: -6.201,
      lon: 106.8015,
    });
  });

  it("throws on a segment with no geometry", () => {
    const empty = segmentGeom({
      fromCode: "AAA",
      toCode: "BBB",
      lengthM: 0,
      coordinates: [],
    });
    expect(() => pointAt(empty, 10)).toThrow();
  });
});

describe("bearing", () => {
  it("matches the Python reference bearings", () => {
    expect(bearing({ lat: -6.2, lon: 106.8 }, { lat: -6.19, lon: 106.8 })).toBeCloseTo(0, 6);
    expect(bearing({ lat: -6.2, lon: 106.8 }, { lat: -6.2, lon: 106.81 })).toBeCloseTo(
      90.00053999677647,
      6,
    );
    expect(bearing({ lat: -6.2, lon: 106.8 }, { lat: -6.21, lon: 106.8 })).toBeCloseTo(180, 6);
  });

  it("is always in [0, 360)", () => {
    const cases: Array<[number, number, number, number]> = [
      [-6.2, 106.8, -6.19, 106.79],
      [-6.2, 106.8, -6.21, 106.81],
      [-6.2, 106.8, -6.2, 106.79],
    ];
    for (const [a, b, c, d] of cases) {
      const value = bearing({ lat: a, lon: b }, { lat: c, lon: d });
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(360);
    }
  });
});
