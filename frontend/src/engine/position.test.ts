/**
 * The position rules from `engine/position.py`. Every case here is a RULE, not
 * a number: the numbers are pinned by the 6,000-frame parity gate instead.
 */
import { describe, expect, it } from "vitest";
import { positionsAt } from "./position";
import { segmentGeom, station, trip, waypoint } from "./testUtils";
import type { Policy, ScheduleSnapshot, SegmentGeom, Trip } from "./types";
import { DEFAULT_POLICY, MOTION_MODEL } from "./types";
import { midnightEpochMs, wibToEpochMs } from "./time";

const SERVICE_DATE = { year: 2026, month: 12, day: 1 } as const;
const midnight = midnightEpochMs(SERVICE_DATE);

/** Two stations ~1112 m apart, north to south. */
const LINE: readonly { lat: number; lon: number }[] = [
  { lat: -6.2, lon: 106.8 },
  { lat: -6.21, lon: 106.8 },
];

function lineSegment(fromCode: string, toCode: string, lengthM = 1111.95): SegmentGeom {
  return segmentGeom({ fromCode, toCode, lengthM, coordinates: LINE });
}

/** A → B: departs at `departA`, arrives at `arriveB`. */
function simpleTrip(overrides: {
  departA?: number;
  arriveB?: number;
  arriveA?: number;
  departB?: number;
  stopTypeB?: "stop" | "pass";
  extra?: Partial<Parameters<typeof trip>[0]>;
}): Trip {
  const departA = overrides.departA ?? 1000;
  const arriveB = overrides.arriveB ?? 1600;
  return trip({
    tripId: "t-simple",
    trainNo: "1",
    name: "Test",
    waypoints: [
      waypoint({
        seq: 0,
        stationCode: "AAA",
        arriveSod: overrides.arriveA ?? departA,
        departSod: departA,
        sM: 0,
      }),
      waypoint({
        seq: 1,
        stationCode: "BBB",
        stopType: overrides.stopTypeB ?? "stop",
        arriveSod: arriveB,
        departSod: overrides.departB ?? arriveB,
        sM: 1111.95,
      }),
    ],
    segments: [lineSegment("AAA", "BBB")],
    firstAbs: departA,
    lastAbs: arriveB,
    ...overrides.extra,
  });
}

function snapshotOf(trips: readonly Trip[], maxDayOffset = 2): ScheduleSnapshot {
  return {
    versionName: "Gapeka 2026",
    effectiveFrom: "2026-12-01",
    effectiveTo: null,
    contentHash: "0000000000000000",
    maxDayOffset,
    policy: DEFAULT_POLICY,
    trips,
    stations: new Map([["AAA", station({ code: "AAA" })], ["BBB", station({ code: "BBB" })]]),
    attribution: { osm: "© OpenStreetMap contributors", osm_url: "", disclaimer: "" },
  };
}

function at(secondsOfDay: number, policy?: Partial<Policy>) {
  return positionsAt(
    snapshotOf([simpleTrip({})]),
    midnight + secondsOfDay * 1000,
    { ...DEFAULT_POLICY, ...policy },
  );
}

describe("status and dwell", () => {
  /**
   * A → B → C with a real dwell at B (arrive 1300, depart 1400).
   *
   * A dwell at the ORIGIN is not testable: `positions_at` filters on
   * `first_abs = first timed departure`, so the train is never reported while it
   * is still standing at its starting platform. That is the reference behaviour.
   */
  const withDwell = trip({
    tripId: "t-dwell",
    trainNo: "3",
    name: "Dwell",
    waypoints: [
      waypoint({ seq: 0, stationCode: "AAA", arriveSod: 1000, departSod: 1000, sM: 0 }),
      waypoint({ seq: 1, stationCode: "BBB", arriveSod: 1300, departSod: 1400, sM: 555 }),
      waypoint({ seq: 2, stationCode: "CCC", arriveSod: 1700, departSod: 1700, sM: 1111.95 }),
    ],
    segments: [lineSegment("AAA", "BBB", 555), lineSegment("BBB", "CCC", 556.95)],
    firstAbs: 1000,
    lastAbs: 1700,
  });
  const dwellSnapshot = snapshotOf([withDwell]);

  it("reports at_station with zero speed during a dwell", () => {
    const positions = positionsAt(dwellSnapshot, midnight + 1350 * 1000, DEFAULT_POLICY);
    expect(positions).toHaveLength(1);
    const position = positions[0]!;
    expect(position.status).toBe("at_station");
    expect(position.sM).toBe(555);
    expect(position.speedKmh).toBe(0);
    expect(position.fromCode).toBe("BBB");
    expect(position.toCode).toBe("CCC");
  });

  it("reports running between the departure and the arrival", () => {
    const positions = at(1300);
    expect(positions).toHaveLength(1);
    const position = positions[0]!;
    expect(position.status).toBe("running");
    expect(position.sM).toBeGreaterThan(0);
    expect(position.sM).toBeLessThan(1111.95);
    expect(position.speedKmh).toBeGreaterThan(0);
  });

  it("is at the origin exactly at the departure second", () => {
    const position = at(1000)[0]!;
    expect(position.status).toBe("at_station");
    expect(position.sM).toBe(0);
  });

  it("is at the destination exactly at the arrival second", () => {
    const position = at(1600)[0]!;
    expect(position.status).toBe("at_station");
    expect(position.sM).toBe(1111.95);
  });

  it("does not return the trip before the first departure", () => {
    expect(at(999)).toHaveLength(0);
  });

  it("does not return the trip after the last arrival", () => {
    expect(at(1601)).toHaveLength(0);
  });

  it("cannot linger past last_abs, exactly like the Python reference", () => {
    // `positions_at` filters on `first_abs <= elapsed <= last_abs` BEFORE
    // `_position_for`, so terminal_linger_s can never extend beyond last_abs.
    // Reproduced faithfully rather than "fixed": a port that invented extra
    // frames would fail parity.
    expect(at(1650, { terminal_linger_s: 60 })).toHaveLength(0);
  });

  it("treats the dwell as arrive <= t < depart", () => {
    // 1399 is still the dwell; 1400 is the departure second and the train moves.
    expect(positionsAt(dwellSnapshot, midnight + 1399 * 1000, DEFAULT_POLICY)[0]!.status).toBe(
      "at_station",
    );
    const departing = positionsAt(dwellSnapshot, midnight + 1400 * 1000, DEFAULT_POLICY)[0]!;
    expect(departing.status).toBe("at_station");
    expect(departing.fromCode).toBe("BBB");
    // One second later it is running.
    const moving = positionsAt(dwellSnapshot, midnight + 1401 * 1000, DEFAULT_POLICY)[0]!;
    expect(moving.status).toBe("running");
  });

  it("marks every position as an estimate with the motion model", () => {
    const position = at(1300)[0]!;
    expect(position.estimated).toBe(true);
    expect(position.motionModel).toBe(MOTION_MODEL);
  });
});

describe("pass rows", () => {
  const passing = simpleTrip({
    extra: {
      waypoints: [
        waypoint({ seq: 0, stationCode: "AAA", arriveSod: 1000, departSod: 1000, sM: 0 }),
        waypoint({
          seq: 1,
          stationCode: "PPP",
          stopType: "pass",
          arriveSod: 1300,
          departSod: 1300,
          sM: 555,
        }),
        waypoint({ seq: 2, stationCode: "BBB", arriveSod: 1600, departSod: 1600, sM: 1111.95 }),
      ],
      segments: [lineSegment("AAA", "PPP", 555), lineSegment("PPP", "BBB", 556.95)],
    },
  });

  const snapshot = snapshotOf([passing]);

  it("creates no dwell at a pass row", () => {
    // One second before and one second after the pass time, the train moves.
    const before = positionsAt(snapshot, midnight + 1299 * 1000, DEFAULT_POLICY)[0]!;
    const after = positionsAt(snapshot, midnight + 1301 * 1000, DEFAULT_POLICY)[0]!;
    expect(before.status).toBe("running");
    expect(after.status).toBe("running");
    expect(after.sM).toBeGreaterThan(before.sM);
  });

  it("keeps the distance continuous across the pass boundary", () => {
    const before = positionsAt(snapshot, midnight + 1299 * 1000, DEFAULT_POLICY)[0]!;
    const after = positionsAt(snapshot, midnight + 1301 * 1000, DEFAULT_POLICY)[0]!;
    // Two seconds of travel: continuous, not a jump.
    expect(Math.abs(after.sM - before.sM)).toBeLessThan(20);
  });

  it("skips a pass row when reporting the next stop", () => {
    const position = positionsAt(snapshot, midnight + 1100 * 1000, DEFAULT_POLICY)[0]!;
    expect(position.nextStopCode).toBe("BBB");
    expect(position.nextStopTime).toBe("00:26:40");
  });
});

describe("untimed rows", () => {
  const withUntimed = trip({
    tripId: "t-untimed",
    trainNo: "2",
    name: "Coarse",
    hasUntimedMarkers: true,
    waypoints: [
      waypoint({ seq: 0, stationCode: "AAA", arriveSod: 1000, departSod: 1000, sM: 0 }),
      waypoint({
        seq: 1,
        stationCode: "PPP",
        stopType: "unknown_untimed",
        arriveSod: null,
        departSod: null,
        sM: 555,
      }),
      waypoint({ seq: 2, stationCode: "BBB", arriveSod: 1600, departSod: 1600, sM: 1111.95 }),
    ],
    segments: [lineSegment("AAA", "PPP", 555), lineSegment("PPP", "BBB", 556.95)],
    firstAbs: 1000,
    lastAbs: 1600,
  });

  it("marks the position coarse", () => {
    const position = positionsAt(snapshotOf([withUntimed]), midnight + 1300 * 1000, DEFAULT_POLICY)[0]!;
    expect(position.coarse).toBe(true);
  });

  it("never creates a pause at an untimed row", () => {
    for (const second of [1200, 1300, 1400]) {
      const position = positionsAt(
        snapshotOf([withUntimed]),
        midnight + second * 1000,
        DEFAULT_POLICY,
      )[0]!;
      expect(position.status).toBe("running");
    }
  });
});

describe("midnight crossing", () => {
  // Departs 23:50, arrives 00:30 the next day (day_offset 1).
  const overnight = trip({
    tripId: "t-night",
    trainNo: "260F",
    name: "Banyubiru",
    waypoints: [
      waypoint({ seq: 0, stationCode: "AAA", arriveSod: 85_800, departSod: 85_800, sM: 0 }),
      waypoint({
        seq: 1,
        stationCode: "BBB",
        arriveSod: 1_800,
        arriveDayOffset: 1,
        departSod: 1_800,
        departDayOffset: 1,
        sM: 1111.95,
      }),
    ],
    segments: [lineSegment("AAA", "BBB")],
    firstAbs: 85_800,
    lastAbs: 86_400 + 1_800,
  });

  const snapshot = snapshotOf([overnight]);

  it("appears after midnight on the following calendar day", () => {
    const nextMidnight = midnight + 86_400 * 1000;
    const positions = positionsAt(snapshot, nextMidnight + 900 * 1000, DEFAULT_POLICY);
    expect(positions).toHaveLength(1);
    expect(positions[0]!.tripId).toBe("t-night");
    expect(positions[0]!.status).toBe("running");
  });

  it("appears only once, not for the service date that has not started", () => {
    const nextMidnight = midnight + 86_400 * 1000;
    const positions = positionsAt(snapshot, nextMidnight + 900 * 1000, DEFAULT_POLICY);
    expect(new Set(positions.map((position) => position.tripId)).size).toBe(1);
  });

  it("is gone once the tail is over", () => {
    const nextMidnight = midnight + 86_400 * 1000;
    expect(positionsAt(snapshot, nextMidnight + 1801 * 1000, DEFAULT_POLICY)).toHaveLength(0);
  });

  it("scans max_day_offset service dates", () => {
    // With maxDayOffset = 0 the previous service date is never considered.
    const nextMidnight = midnight + 86_400 * 1000;
    const noTail = snapshotOf([overnight], 0);
    expect(positionsAt(noTail, nextMidnight + 900 * 1000, DEFAULT_POLICY)).toHaveLength(0);
  });
});

describe("visibility", () => {
  const fakultatif = simpleTrip({
    extra: { tripId: "t-fak", trainNo: "260F", serviceClass: "fakultatif" },
  });
  const unknownClass = simpleTrip({ extra: { tripId: "t-unknown", serviceClass: "unknown" } });
  const reguler = simpleTrip({ extra: { tripId: "t-reg" } });

  const snapshot = snapshotOf([fakultatif, unknownClass, reguler]);
  const instant = midnight + 1300 * 1000;

  it("hides fakultatif trips by default", () => {
    const ids = positionsAt(snapshot, instant, DEFAULT_POLICY).map((position) => position.tripId);
    expect(ids).toEqual(["t-reg"]);
  });

  it("treats an unknown service class like fakultatif", () => {
    const ids = positionsAt(snapshot, instant, { ...DEFAULT_POLICY, show_fakultatif: true }).map(
      (position) => position.tripId,
    );
    expect(ids).toContain("t-unknown");
    expect(ids).toContain("t-fak");
  });

  it("shows fakultatif trips when the policy allows it", () => {
    const ids = positionsAt(snapshot, instant, { ...DEFAULT_POLICY, show_fakultatif: true }).map(
      (position) => position.tripId,
    );
    expect(ids).toHaveLength(3);
  });

  it("never shows has_unmeasured under any geometry policy", () => {
    const unmeasured = simpleTrip({ extra: { tripId: "t-un", geometryStatus: "has_unmeasured" } });
    const withUnmeasured = snapshotOf([unmeasured]);
    for (const geometry_policy of [
      "complete_and_estimated",
      "complete_only",
      "allow_fallback",
    ] as const) {
      const positions = positionsAt(withUnmeasured, instant, {
        ...DEFAULT_POLICY,
        geometry_policy,
        show_fakultatif: true,
      });
      expect(positions).toHaveLength(0);
    }
  });

  it("shows complete_estimated by default but hides it under complete_only", () => {
    const estimated = simpleTrip({
      extra: { tripId: "t-est", geometryStatus: "complete_estimated" },
    });
    const snapshot = snapshotOf([estimated]);
    expect(positionsAt(snapshot, instant, DEFAULT_POLICY)).toHaveLength(1);
    expect(
      positionsAt(snapshot, instant, { ...DEFAULT_POLICY, geometry_policy: "complete_only" }),
    ).toHaveLength(0);
  });

  it("adds has_fallback trips only under allow_fallback", () => {
    const fallback = simpleTrip({ extra: { tripId: "t-fb", geometryStatus: "has_fallback" } });
    const snapshot = snapshotOf([fallback]);
    expect(positionsAt(snapshot, instant, DEFAULT_POLICY)).toHaveLength(0);
    expect(
      positionsAt(snapshot, instant, { ...DEFAULT_POLICY, geometry_policy: "allow_fallback" }),
    ).toHaveLength(1);
  });
});

describe("policy defaults", () => {
  it("does not treat calendar_policy or enforce_effective_from as a gate", () => {
    // Mirrors Python: these fields are declared but positions_at ignores them.
    // The effective-date gate is `isScheduleActive`, used by the UI.
    const before = wibToEpochMs({ year: 2026, month: 11, day: 1 }, 1300);
    const positions = positionsAt(snapshotOf([simpleTrip({})]), before, {
      ...DEFAULT_POLICY,
      enforce_effective_from: true,
    });
    expect(positions).toHaveLength(1);
  });
});
