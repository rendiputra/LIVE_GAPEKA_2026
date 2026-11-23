/**
 * The export stores each segment once, polyline-encoded at precision 6
 * (`pipeline/export_web.py:encode_polyline`). The decoder must invert it exactly.
 *
 * The fixture strings below were produced by the Python encoder, so this is a
 * cross-language check, not a self-consistency check.
 */
import { describe, expect, it } from "vitest";
import { decodePolyline } from "./polyline";

describe("decodePolyline", () => {
  it("decodes an empty string to no points", () => {
    expect(decodePolyline("", 6)).toEqual([]);
  });

  it("decodes a single point (encoded by the Python exporter)", () => {
    expect(decodePolyline("~jlyJ_wpujE", 6)).toEqual([{ lat: -6.2, lon: 106.8 }]);
  });

  it("decodes a multi-point line with negative deltas and a zero crossing", () => {
    const points = decodePolyline("~jlyJ_wpujEn}@w|Av|Aw|AggqyJnrvujE~~ggN_yokyE", 6);
    expect(points).toHaveLength(5);
    expect(points[0]).toEqual({ lat: -6.2, lon: 106.8 });
    expect(points[1]?.lat).toBeCloseTo(-6.201, 6);
    expect(points[1]?.lon).toBeCloseTo(106.8015, 6);
    expect(points[2]?.lat).toBeCloseTo(-6.2025, 6);
    expect(points[2]?.lon).toBeCloseTo(106.803, 6);
    expect(points[3]).toEqual({ lat: 0, lon: 0 });
    expect(points[4]).toEqual({ lat: -8, lon: 114.5 });
  });

  it("honours the precision argument", () => {
    // precision 5 divides the same integer deltas by 10.
    const at5 = decodePolyline("~jlyJ_wpujE", 5);
    expect(at5[0]?.lat).toBeCloseTo(-62, 6);
  });

  it("rejects a truncated string instead of returning partial data", () => {
    expect(() => decodePolyline("~jlyJ_wpuj", 6)).toThrow();
  });
});
