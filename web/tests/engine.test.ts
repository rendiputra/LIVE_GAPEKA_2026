// Unit tests for the ported maths. These mirror the Python P1 hand-calculations
// so a refactor cannot silently change the motion model.

import { describe, expect, it } from "vitest";

import { buildLeg, distanceAt, speedAt } from "../src/engine/profile";
import { buildSegment, cumulativeM, decodePolyline, haversineM, pointAt } from "../src/engine/polyline";

describe("trapezoid_v1", () => {
  it("uses v = L / (D - a_s/2 - a_e/2)", () => {
    const leg = buildLeg(0, 600, 0, 10_000, true, true, 60);
    expect(leg).not.toBeNull();
    expect(leg!.cruiseMps).toBeCloseTo(10_000 / 540, 9);
  });

  it("is symmetric: half the time gives half the distance", () => {
    const leg = buildLeg(0, 600, 0, 10_000, true, true, 60)!;
    expect(distanceAt(leg, 300)).toBeCloseTo(5000, 6);
  });

  it("reaches the endpoint exactly", () => {
    const leg = buildLeg(0, 600, 0, 10_000, true, true, 60)!;
    expect(distanceAt(leg, 600)).toBe(10_000);
  });

  it("has no ease at a pass end", () => {
    const leg = buildLeg(0, 600, 0, 10_000, true, false, 60)!;
    expect(leg.easeEndS).toBe(0);
    expect(speedAt(leg, 599)).toBeCloseTo(leg.cruiseMps, 9);
  });

  it("rejects a degenerate leg", () => {
    expect(buildLeg(0, 0, 0, 100, true, true, 60)).toBeNull();
    expect(buildLeg(0, 60, 100, 100, true, true, 60)).toBeNull();
  });

  it("never exceeds the cruise speed", () => {
    const leg = buildLeg(0, 600, 0, 10_000, true, true, 60)!;
    for (let t = 0; t <= 600; t += 1) {
      expect(speedAt(leg, t)).toBeLessThanOrEqual(leg.cruiseMps + 1e-9);
      expect(speedAt(leg, t)).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("polyline and lookup", () => {
  it("round-trips a polyline encoded by the Python exporter", () => {
    // `pipeline.export_web.encode_polyline([(-7.0,110.0),(-6.999,110.001)])`
    const points = decodePolyline("~zfjL_wzxpEo}@o}@");
    expect(points.length).toBe(2);
    expect(points[0][0]).toBeCloseTo(-7.0, 6);
    expect(points[0][1]).toBeCloseTo(110.0, 6);
    expect(points[1][0]).toBeCloseTo(-6.999, 6);
    expect(points[1][1]).toBeCloseTo(110.001, 6);
  });

  it("clamps to the polyline length, not length_m", () => {
    const encoded = "~zfjL_wzxpEo}@o}@";
    const segment = buildSegment(
      { from: "A", to: "B", length_m: 1e9, polyline: encoded },
      false,
    );
    const end = pointAt(segment, 1e8);
    const last = segment.points[segment.points.length - 1];
    expect(end).toEqual(last);
  });

  it("reverses the geometry and swaps the endpoints", () => {
    const encoded = "~zfjL_wzxpEo}@o}@";
    const forward = buildSegment({ from: "A", to: "B", length_m: 1, polyline: encoded }, false);
    const backward = buildSegment({ from: "A", to: "B", length_m: 1, polyline: encoded }, true);
    expect(backward.from).toBe("B");
    expect(backward.to).toBe("A");
    expect(backward.points[0]).toEqual(forward.points[forward.points.length - 1]);
  });

  it("cumulative distance is non-decreasing", () => {
    const points = decodePolyline("~zfjL_wzxpEo}@o}@");
    const cumulative = cumulativeM(points);
    for (let i = 1; i < cumulative.length; i += 1) {
      expect(cumulative[i]).toBeGreaterThanOrEqual(cumulative[i - 1]);
    }
  });

  it("haversine matches a known short distance", () => {
    // 0.001 deg of latitude near 7 S is about 111.2 m.
    const distance = haversineM([-7.0, 110.0], [-6.999, 110.0]);
    expect(distance).toBeGreaterThan(110);
    expect(distance).toBeLessThan(112);
  });
});
