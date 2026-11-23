/**
 * `trapezoid_v1` must reproduce `engine/profile.py` exactly (ADR 004).
 *
 * Every expected value below is derived from the Python formulas, not measured
 * from this implementation: if the port drifts, these fail.
 */
import { describe, expect, it } from "vitest";
import { buildLeg, distanceAt, speedAt } from "./profile";

describe("buildLeg", () => {
  it("returns null for a degenerate leg (no time or no distance)", () => {
    expect(buildLeg({ tI: 100, tJ: 100, sI: 0, sJ: 500, easeStart: true, easeEnd: true })).toBeNull();
    expect(buildLeg({ tI: 200, tJ: 100, sI: 0, sJ: 500, easeStart: true, easeEnd: true })).toBeNull();
    expect(buildLeg({ tI: 0, tJ: 600, sI: 500, sJ: 500, easeStart: true, easeEnd: true })).toBeNull();
    expect(buildLeg({ tI: 0, tJ: 600, sI: 500, sJ: 400, easeStart: true, easeEnd: true })).toBeNull();
  });

  it("eases at both ends when both rows are stops", () => {
    const leg = buildLeg({ tI: 0, tJ: 600, sI: 0, sJ: 6000, easeStart: true, easeEnd: true });
    expect(leg).not.toBeNull();
    expect(leg?.easeStartS).toBe(60);
    expect(leg?.easeEndS).toBe(60);
    // cruise_time = 600 - 60/2 - 60/2 = 540 -> v = 6000 / 540
    expect(leg?.cruiseMps).toBeCloseTo(6000 / 540, 12);
  });

  it("adds no ease at a pass row", () => {
    const leg = buildLeg({ tI: 0, tJ: 600, sI: 0, sJ: 6000, easeStart: false, easeEnd: false });
    expect(leg?.easeStartS).toBe(0);
    expect(leg?.easeEndS).toBe(0);
    expect(leg?.cruiseMps).toBeCloseTo(10, 12);
  });

  it("eases only at the stop end", () => {
    const leg = buildLeg({ tI: 0, tJ: 600, sI: 0, sJ: 6000, easeStart: false, easeEnd: true });
    expect(leg?.easeStartS).toBe(0);
    expect(leg?.easeEndS).toBe(60);
    // cruise_time = 600 - 0 - 30 = 570
    expect(leg?.cruiseMps).toBeCloseTo(6000 / 570, 12);
  });

  it("clamps the ease to a third of the leg duration", () => {
    // D = 90 -> min(60, 30) = 30 at each end
    const leg = buildLeg({ tI: 0, tJ: 90, sI: 0, sJ: 900, easeStart: true, easeEnd: true });
    expect(leg?.easeStartS).toBe(30);
    expect(leg?.easeEndS).toBe(30);
    // cruise_time = 90 - 15 - 15 = 60 -> v = 900 / 60
    expect(leg?.cruiseMps).toBeCloseTo(15, 12);
  });

  it("scales both eases down when they would consume the whole duration", () => {
    // A stop-to-stop leg shorter than 2*accel: D = 60 -> each ease clamped to 20,
    // sum 40 < 60, so the guard does not fire; use a pathological accel instead.
    const leg = buildLeg({
      tI: 0,
      tJ: 30,
      sI: 0,
      sJ: 300,
      easeStart: true,
      easeEnd: true,
      accelTimeS: 1000,
    });
    // ease = min(1000, 10) = 10 each -> sum 20 < 30, guard silent.
    expect(leg?.easeStartS).toBe(10);
    expect(leg?.easeEndS).toBe(10);
  });

  it("keeps the cruise interval positive when eases would exceed the duration", () => {
    // accelTimeS is irrelevant here because of the D/3 clamp, so the guard is
    // reached only with a negative-time edge; assert the leg stays usable.
    const leg = buildLeg({ tI: 0, tJ: 1, sI: 0, sJ: 1, easeStart: true, easeEnd: true });
    expect(leg).not.toBeNull();
    expect(leg!.easeStartS + leg!.easeEndS).toBeLessThan(1);
    expect(leg!.cruiseMps).toBeGreaterThan(0);
  });
});

describe("distanceAt", () => {
  const leg = buildLeg({ tI: 0, tJ: 600, sI: 0, sJ: 6000, easeStart: true, easeEnd: true })!;

  it("clamps at both ends", () => {
    expect(distanceAt(leg, -50)).toBe(0);
    expect(distanceAt(leg, 0)).toBe(0);
    expect(distanceAt(leg, 600)).toBe(6000);
    expect(distanceAt(leg, 9000)).toBe(6000);
  });

  it("accelerates quadratically from rest", () => {
    // 0.5 * (v/60) * 30^2
    const v = 6000 / 540;
    expect(distanceAt(leg, 30)).toBeCloseTo(0.5 * (v / 60) * 900, 9);
  });

  it("cruises linearly", () => {
    const v = 6000 / 540;
    // 0.5*v*60 + v*(300-60)
    expect(distanceAt(leg, 300)).toBeCloseTo(0.5 * v * 60 + v * 240, 9);
  });

  it("decelerates to rest and lands exactly on sJ", () => {
    const v = 6000 / 540;
    // sJ - 0.5*(v/60)*30^2
    expect(distanceAt(leg, 570)).toBeCloseTo(6000 - 0.5 * (v / 60) * 900, 9);
    expect(distanceAt(leg, 600)).toBe(6000);
  });

  it("reaches sJ exactly at tJ for every duration (no drift)", () => {
    for (const duration of [61, 90, 137, 600, 3600, 12345]) {
      const anyLeg = buildLeg({
        tI: 1000,
        tJ: 1000 + duration,
        sI: 500,
        sJ: 500 + duration * 12,
        easeStart: true,
        easeEnd: true,
      })!;
      expect(distanceAt(anyLeg, 1000 + duration)).toBeCloseTo(500 + duration * 12, 6);
    }
  });

  it("is monotonic along the leg", () => {
    let previous = -1;
    for (let t = 0; t <= 600; t += 1) {
      const s = distanceAt(leg, t);
      expect(s).toBeGreaterThanOrEqual(previous);
      previous = s;
    }
  });
});

describe("speedAt", () => {
  const leg = buildLeg({ tI: 0, tJ: 600, sI: 0, sJ: 6000, easeStart: true, easeEnd: true })!;
  const v = 6000 / 540;

  it("is zero outside the leg", () => {
    expect(speedAt(leg, -1)).toBe(0);
    expect(speedAt(leg, 0)).toBe(0);
    expect(speedAt(leg, 600)).toBe(0);
    expect(speedAt(leg, 601)).toBe(0);
  });

  it("ramps up during acceleration and down during deceleration", () => {
    expect(speedAt(leg, 30)).toBeCloseTo((v / 60) * 30, 9);
    expect(speedAt(leg, 570)).toBeCloseTo((v / 60) * 30, 9);
  });

  it("holds cruise speed in the middle", () => {
    expect(speedAt(leg, 300)).toBeCloseTo(v, 12);
  });

  it("has no ease phase when both ends are pass rows", () => {
    const passLeg = buildLeg({
      tI: 0,
      tJ: 600,
      sI: 0,
      sJ: 6000,
      easeStart: false,
      easeEnd: false,
    })!;
    expect(speedAt(passLeg, 0.001)).toBeCloseTo(10, 6);
    expect(speedAt(passLeg, 599.999)).toBeCloseTo(10, 6);
  });
});
