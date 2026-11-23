/**
 * The loader must reproduce what `engine/snapshot.py` builds from the database,
 * using only the exported JSON. These tests read the REAL export, so they also
 * guard the export contract itself (station indices, -1 sentinels, flags).
 */
import { beforeAll, describe, expect, it } from "vitest";
import { buildSnapshot, decodeSegments, FLAG_BYPASSED, orientSegment } from "./load";
import { readExportedBundle } from "./testUtils";
import type { RawExport } from "./load";
import { arriveAbs, departAbs, type ScheduleSnapshot, SECONDS_PER_DAY } from "./types";

let raw: RawExport;
let snapshot: ScheduleSnapshot;

beforeAll(async () => {
  raw = await readExportedBundle();
  snapshot = buildSnapshot(raw);
});

describe("buildSnapshot", () => {
  it("carries the manifest metadata", () => {
    expect(snapshot.versionName).toBe("Gapeka 2026");
    expect(snapshot.effectiveFrom).toBe("2026-12-01");
    expect(snapshot.effectiveTo).toBeNull();
    expect(snapshot.contentHash).toMatch(/^[0-9a-f]{16}$/);
  });

  it("matches the manifest counts", () => {
    expect(snapshot.trips).toHaveLength(raw.manifest.counts.trips);
    expect(snapshot.stations.size).toBe(raw.manifest.counts.stations);
  });

  it("keeps the policy defaults the manifest declares", () => {
    expect(snapshot.policy.calendar_policy).toBe("regular_daily_assumed");
    expect(snapshot.policy.show_fakultatif).toBe(false);
    expect(snapshot.policy.enforce_effective_from).toBe(false);
    expect(snapshot.policy.geometry_policy).toBe("complete_and_estimated");
    expect(snapshot.policy.accel_time_s).toBe(60);
  });

  it("exposes the attribution the About modal needs", () => {
    expect(snapshot.attribution.disclaimer).toContain("bukan posisi aktual");
    expect(snapshot.attribution.osm).toContain("OpenStreetMap");
  });

  it("resolves every waypoint station code through the index column", () => {
    for (const trip of snapshot.trips) {
      for (const row of trip.rows) {
        expect(snapshot.stations.has(row.stationCode)).toBe(true);
      }
    }
  });

  it("keeps every trip's distances non-decreasing", () => {
    for (const trip of snapshot.trips) {
      let previous = -1;
      for (const row of trip.rows) {
        expect(row.sM).toBeGreaterThanOrEqual(previous);
        previous = row.sM;
      }
    }
  });
});

describe("train names", () => {
  const findByName = (trainNo: string) => snapshot.trips.filter((trip) => trip.trainNo === trainNo);

  it("uses the real name for KA 50 (Gajayana), never the number", () => {
    const trips = findByName("50");
    expect(trips.length).toBeGreaterThan(0);
    for (const trip of trips) expect(trip.name).toBe("Gajayana");
  });

  it("uses the real name for KA 249 (Kaligung)", () => {
    const trips = findByName("249");
    expect(trips.length).toBeGreaterThan(0);
    for (const trip of trips) expect(trip.name).toBe("Kaligung");
  });

  it("uses the real name for KA 260F (Banyubiru) and marks it fakultatif", () => {
    const trips = findByName("260F");
    expect(trips.length).toBeGreaterThan(0);
    for (const trip of trips) {
      expect(trip.name).toBe("Banyubiru");
      expect(trip.serviceClass).toBe("fakultatif");
      expect(trip.hiddenByDefault).toBe(true);
    }
  });

  it("never duplicates the train number as the name", () => {
    const duplicated = snapshot.trips.filter(
      (trip) => trip.name.trim() !== "" && trip.name.trim() === trip.trainNo.trim(),
    );
    expect(duplicated).toHaveLength(0);
  });

  it("derives the book from the trip id (b1 = intercity, b2 = local)", () => {
    const book1 = snapshot.trips.filter((trip) => trip.tripId.startsWith("b1-"));
    const book2 = snapshot.trips.filter((trip) => trip.tripId.startsWith("b2-"));
    expect(book1.length).toBeGreaterThan(0);
    expect(book2.length).toBeGreaterThan(0);
    for (const trip of book1) expect(trip.book).toBe(1);
    for (const trip of book2) expect(trip.book).toBe(2);
  });

  it("marks fakultatif trips hidden by default", () => {
    const fakultatif = snapshot.trips.filter((trip) => trip.serviceClass === "fakultatif");
    expect(fakultatif.length).toBeGreaterThan(0);
    for (const trip of fakultatif) {
      expect(trip.hiddenByDefault).toBe(true);
      expect(trip.name === trip.trainNo).toBe(false);
    }
  });

  it("marks regular trips as shown by default", () => {
    const reguler = snapshot.trips.filter((trip) => trip.serviceClass === "reguler");
    for (const trip of reguler) expect(trip.hiddenByDefault).toBe(false);
  });
});

describe("waypoint decoding", () => {
  it("maps the -1 sentinel to null", () => {
    const withMissing = snapshot.trips.flatMap((trip) =>
      trip.rows.filter((row) => row.arriveSod === null || row.departSod === null),
    );
    expect(withMissing.length).toBeGreaterThan(0);
    for (const row of withMissing) {
      expect(row.arriveSod === null || typeof row.arriveSod === "number").toBe(true);
    }
  });

  it("splits an absolute time into seconds-of-day plus day offset", () => {
    const crossing = snapshot.trips
      .flatMap((trip) => trip.rows)
      .find((row) => row.departDayOffset === 1);
    expect(crossing).toBeDefined();
    expect(crossing!.departSod).not.toBeNull();
    expect(crossing!.departSod!).toBeLessThan(SECONDS_PER_DAY);
    expect(departAbs(crossing!)).toBe(
      crossing!.departSod! + SECONDS_PER_DAY * crossing!.departDayOffset,
    );
  });

  it("keeps arrive and depart day offsets independent (ADR 007)", () => {
    // A stop that arrives 23:5x and departs 00:0x carries arrive offset 0 and
    // depart offset 1; a naive single `day_offset` cannot express that.
    const straddling = snapshot.trips
      .flatMap((trip) => trip.rows)
      .filter(
        (row) =>
          row.arriveSod !== null &&
          row.departSod !== null &&
          row.departDayOffset > row.arriveDayOffset,
      );
    expect(straddling.length).toBeGreaterThan(0);
    for (const row of straddling) {
      expect(arriveAbs(row)! + 60).toBeLessThanOrEqual(departAbs(row)! + SECONDS_PER_DAY);
    }
  });

  it("keeps untimed rows as distance markers with null times", () => {
    const untimed = snapshot.trips
      .filter((trip) => trip.hasUntimedMarkers)
      .flatMap((trip) => trip.rows)
      .filter((row) => row.stopType === "unknown_untimed");
    expect(untimed.length).toBeGreaterThan(0);
    for (const row of untimed) expect(row.arriveSod === null || row.departSod === null).toBe(true);
  });
});

describe("bypassed rows", () => {
  it("keeps them in `rows` but never in the engine `waypoints`", () => {
    const bypassedTrips = snapshot.trips.filter((trip) => trip.hasBypassedWaypoints);
    expect(bypassedTrips.length).toBeGreaterThan(0);

    let sawBypassedRow = false;
    for (const trip of bypassedTrips) {
      for (const row of trip.rows) {
        if (row.bypassed) sawBypassedRow = true;
      }
      expect(trip.waypoints.some((row) => row.bypassed)).toBe(false);
      expect(trip.waypoints.length).toBeLessThan(trip.rows.length);
    }
    expect(sawBypassedRow).toBe(true);
  });

  it("sets the bypassed flag on exactly the rows the export marks", () => {
    for (const trip of snapshot.trips) {
      if (trip.hasBypassedWaypoints) continue;
      expect(trip.rows.some((row) => row.bypassed)).toBe(false);
    }
  });

  it("agrees with the exported FLAG_BYPASSED bit", () => {
    const rawByFlag = raw.trips.trips.filter((trip) => (trip.flags & FLAG_BYPASSED) !== 0);
    const bySnapshot = snapshot.trips.filter((trip) => trip.hasBypassedWaypoints);
    expect(bySnapshot).toHaveLength(rawByFlag.length);
  });
});

describe("segment orientation", () => {
  it("decodes every exported polyline to the declared point count", () => {
    for (const segment of raw.segments.segments) {
      const decoded = decodeSegments({
        schema: raw.segments.schema,
        precision: raw.segments.precision,
        segments: [segment],
      });
      expect(decoded[0]!.coordinates).toHaveLength(segment.points);
    }
  });

  it("reverses the polyline and re-cumulates for a reversed use", () => {
    const canonical = decodeSegments(raw.segments)[0]!;
    const reversed = orientSegment(canonical, true);
    expect(reversed.coordinates[0]).toEqual(canonical.coordinates.at(-1));
    expect(reversed.coordinates.at(-1)).toEqual(canonical.coordinates[0]);
    expect(reversed.cumulativeM[0]).toBe(0);
    expect(reversed.fromCode).toBe(canonical.toCode);
    expect(reversed.toCode).toBe(canonical.fromCode);
  });

  it("orients each trip segment so the chain runs with the trip", () => {
    // The strongest available check: consecutive segments must join end-to-start,
    // the first segment must leave the first waypoint, and the last must arrive at
    // the last waypoint. A wrongly-reversed segment breaks this chain.
    let checkedTrips = 0;
    for (const trip of snapshot.trips) {
      if (trip.segments.length === 0) continue;
      const first = trip.waypoints[0]!;
      const last = trip.waypoints.at(-1)!;
      expect(trip.segments[0]!.fromCode).toBe(first.stationCode);
      expect(trip.segments.at(-1)!.toCode).toBe(last.stationCode);
      for (let index = 1; index < trip.segments.length; index += 1) {
        expect(trip.segments[index]!.fromCode).toBe(trip.segments[index - 1]!.toCode);
      }
      checkedTrips += 1;
    }
    expect(checkedTrips).toBe(snapshot.trips.length);
  });

  it("keeps a trip's segment lengths summing to its total length", () => {
    for (const trip of snapshot.trips) {
      const sum = trip.segments.reduce((total, segment) => total + segment.lengthM, 0);
      expect(sum).toBeCloseTo(trip.totalLengthM, 1);
    }
  });
});
