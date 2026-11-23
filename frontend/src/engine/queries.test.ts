/**
 * Query helpers the UI needs on top of `positionsAt`: a station departure
 * board and the "next stop + ETA" headline.
 *
 * These have no Python counterpart, so the tests define the behaviour. They are
 * pure functions over the snapshot: no fetching, no clock.
 */
import { describe, expect, it } from "vitest";
import { nextStopAhead, stationBoard } from "./queries";
import { segmentGeom, station, trip, waypoint } from "./testUtils";
import { DEFAULT_POLICY, type ScheduleSnapshot, type Trip } from "./types";
import { midnightEpochMs, wibToEpochMs } from "./time";

const SERVICE_DATE = { year: 2026, month: 12, day: 1 } as const;
const midnight = midnightEpochMs(SERVICE_DATE);

const LINE = [
  { lat: -6.2, lon: 106.8 },
  { lat: -6.21, lon: 106.8 },
];

/** AAA -> BBB -> CCC, departing 08:00 / 08:20 / 08:40. */
function sampleTrip(overrides: Partial<Parameters<typeof trip>[0]> = {}): Trip {
  return trip({
    tripId: "t-board",
    trainNo: "50",
    name: "Gajayana",
    relation: "AAA-CCC",
    waypoints: [
      waypoint({ seq: 0, stationCode: "AAA", arriveSod: 28_800, departSod: 28_800, sM: 0 }),
      waypoint({ seq: 1, stationCode: "BBB", arriveSod: 30_000, departSod: 30_000, sM: 555 }),
      waypoint({ seq: 2, stationCode: "CCC", arriveSod: 31_200, departSod: 31_200, sM: 1111.95 }),
    ],
    segments: [
      segmentGeom({ fromCode: "AAA", toCode: "BBB", lengthM: 555, coordinates: LINE }),
      segmentGeom({ fromCode: "BBB", toCode: "CCC", lengthM: 556.95, coordinates: LINE }),
    ],
    firstAbs: 28_800,
    lastAbs: 31_200,
    ...overrides,
  });
}

function snapshotOf(trips: readonly Trip[]): ScheduleSnapshot {
  return {
    versionName: "Gapeka 2026",
    effectiveFrom: "2026-12-01",
    effectiveTo: null,
    contentHash: "0000000000000000",
    maxDayOffset: 1,
    policy: DEFAULT_POLICY,
    trips,
    stations: new Map([
      ["AAA", station({ code: "AAA", officialName: "Alpha" })],
      ["BBB", station({ code: "BBB", officialName: "Bravo" })],
      ["CCC", station({ code: "CCC", officialName: "Charlie" })],
    ]),
    attribution: { osm: "© OpenStreetMap contributors", osm_url: "", disclaimer: "" },
  };
}

describe("stationBoard", () => {
  const snapshot = snapshotOf([sampleTrip()]);

  it("lists the departures from a station in time order", () => {
    // 07:00, three hours before the 08:00 departure.
    const board = stationBoard(snapshot, "AAA", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(1);
    expect(board[0]!.trainNo).toBe("50");
    expect(board[0]!.name).toBe("Gajayana");
    expect(board[0]!.scheduledTime).toBe("08:00");
  });

  it("prints the station-local printed time, not a UTC one", () => {
    const board = stationBoard(snapshot, "BBB", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board[0]!.scheduledTime).toBe("08:20");
  });

  it("excludes a departure that has already gone", () => {
    // 08:01 — the 08:00 departure from AAA is in the past.
    const board = stationBoard(snapshot, "AAA", midnight + (8 * 3600 + 60) * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(0);
  });

  it("includes a departure exactly at the query instant", () => {
    const board = stationBoard(snapshot, "AAA", midnight + 8 * 3600 * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(1);
  });

  it("respects the three-hour window", () => {
    // 04:59 is 3h01m before the departure.
    const board = stationBoard(snapshot, "AAA", midnight + (4 * 3600 + 59 * 60) * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(0);
    // 05:00 is exactly 3h before: inside the window.
    expect(
      stationBoard(snapshot, "AAA", midnight + 5 * 3600 * 1000, DEFAULT_POLICY),
    ).toHaveLength(1);
  });

  it("never lists a terminus as a boardable departure", () => {
    const board = stationBoard(snapshot, "CCC", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(0);
  });

  it("skips a station the trip only passes through", () => {
    const passing = trip({
      tripId: "t-pass",
      trainNo: "99",
      name: "Passer",
      waypoints: [
        waypoint({ seq: 0, stationCode: "AAA", arriveSod: 28_800, departSod: 28_800, sM: 0 }),
        waypoint({
          seq: 1,
          stationCode: "BBB",
          stopType: "pass",
          arriveSod: 30_000,
          departSod: 30_000,
          sM: 555,
        }),
        waypoint({ seq: 2, stationCode: "CCC", arriveSod: 31_200, departSod: 31_200, sM: 1111.95 }),
      ],
      segments: [
        segmentGeom({ fromCode: "AAA", toCode: "BBB", lengthM: 555, coordinates: LINE }),
        segmentGeom({ fromCode: "BBB", toCode: "CCC", lengthM: 556.95, coordinates: LINE }),
      ],
      firstAbs: 28_800,
      lastAbs: 31_200,
    });
    const board = stationBoard(snapshotOf([passing]), "BBB", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(0);
  });

  it("hides fakultatif trips unless the policy shows them", () => {
    const fak = sampleTrip({ tripId: "t-fak", trainNo: "260F", serviceClass: "fakultatif" });
    const snapshot = snapshotOf([fak]);
    expect(stationBoard(snapshot, "AAA", midnight + 7 * 3600 * 1000, DEFAULT_POLICY)).toHaveLength(
      0,
    );
    expect(
      stationBoard(snapshot, "AAA", midnight + 7 * 3600 * 1000, {
        ...DEFAULT_POLICY,
        show_fakultatif: true,
      }),
    ).toHaveLength(1);
  });

  it("caps the board at ten entries", () => {
    const many = Array.from({ length: 14 }, (_, index) =>
      sampleTrip({
        tripId: `t-${index}`,
        trainNo: String(100 + index),
        // one departure every ten minutes from 08:00
        waypoints: [
          waypoint({
            seq: 0,
            stationCode: "AAA",
            arriveSod: 28_800 + index * 600,
            departSod: 28_800 + index * 600,
            sM: 0,
          }),
          waypoint({
            seq: 1,
            stationCode: "BBB",
            arriveSod: 30_000 + index * 600,
            departSod: 30_000 + index * 600,
            sM: 555,
          }),
        ],
        segments: [segmentGeom({ fromCode: "AAA", toCode: "BBB", lengthM: 555, coordinates: LINE })],
        firstAbs: 28_800 + index * 600,
        lastAbs: 30_000 + index * 600,
      }),
    );
    const board = stationBoard(snapshotOf(many), "AAA", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(10);
    // earliest ten, in order
    expect(board.map((entry) => entry.scheduledTime)).toEqual([
      "08:00",
      "08:10",
      "08:20",
      "08:30",
      "08:40",
      "08:50",
      "09:00",
      "09:10",
      "09:20",
      "09:30",
    ]);
  });

  it("finds an after-midnight departure belonging to the next service date", () => {
    // Departs 01:00 as its own service, queried at 23:30 the night before.
    const early = sampleTrip({
      tripId: "t-early",
      trainNo: "7",
      waypoints: [
        waypoint({ seq: 0, stationCode: "AAA", arriveSod: 3_600, departSod: 3_600, sM: 0 }),
        waypoint({ seq: 1, stationCode: "BBB", arriveSod: 5_400, departSod: 5_400, sM: 555 }),
      ],
      segments: [segmentGeom({ fromCode: "AAA", toCode: "BBB", lengthM: 555, coordinates: LINE })],
      firstAbs: 3_600,
      lastAbs: 5_400,
    });
    const snapshot = snapshotOf([early]);
    const board = stationBoard(snapshot, "AAA", midnight + 23.5 * 3600 * 1000, DEFAULT_POLICY);
    expect(board).toHaveLength(1);
    expect(board[0]!.scheduledTime).toBe("01:00");
    expect(board[0]!.dayOffset).toBe(1);
  });

  it("carries the estimate flags so the UI can label a coarse trip", () => {
    const coarse = sampleTrip({ tripId: "t-coarse", hasUntimedMarkers: true });
    const board = stationBoard(snapshotOf([coarse]), "AAA", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board[0]!.coarse).toBe(true);
  });

  it("returns nothing for an unknown station code", () => {
    expect(stationBoard(snapshot, "ZZZ", midnight, DEFAULT_POLICY)).toHaveLength(0);
  });
});

describe("nextStopAhead", () => {
  const snapshot = snapshotOf([sampleTrip()]);
  const theTrip = snapshot.trips[0]!;

  it("returns the next stop with its printed time and minutes away", () => {
    // 07:50, still before departure; next stop is BBB at 08:20.
    const next = nextStopAhead(theTrip, 0, 7 * 3600 + 50 * 60);
    expect(next).not.toBeNull();
    expect(next!.code).toBe("BBB");
    expect(next!.scheduledTime).toBe("08:20");
    expect(next!.minutesAway).toBe(30);
  });

  it("skips pass rows in favour of the next real stop", () => {
    const passing = trip({
      tripId: "t-pass2",
      trainNo: "99",
      name: "Passer",
      waypoints: [
        waypoint({ seq: 0, stationCode: "AAA", arriveSod: 28_800, departSod: 28_800, sM: 0 }),
        waypoint({
          seq: 1,
          stationCode: "PPP",
          stopType: "pass",
          arriveSod: 30_000,
          departSod: 30_000,
          sM: 555,
        }),
        waypoint({ seq: 2, stationCode: "CCC", arriveSod: 31_200, departSod: 31_200, sM: 1111.95 }),
      ],
      segments: [
        segmentGeom({ fromCode: "AAA", toCode: "PPP", lengthM: 555, coordinates: LINE }),
        segmentGeom({ fromCode: "PPP", toCode: "CCC", lengthM: 556.95, coordinates: LINE }),
      ],
      firstAbs: 28_800,
      lastAbs: 31_200,
    });
    const next = nextStopAhead(passing, 0, 28_800);
    expect(next!.code).toBe("CCC");
    expect(next!.scheduledTime).toBe("08:40");
  });

  it("never rounds a negative remaining time into a positive ETA", () => {
    const next = nextStopAhead(theTrip, 0, 31_200);
    // Past the last stop: nothing ahead.
    expect(next).toBeNull();
  });

  it("returns null when the train is already at the final stop", () => {
    expect(nextStopAhead(theTrip, 1111.95, 31_200)).toBeNull();
  });

  it("keeps a fractional minute honest (floors, never rounds up)", () => {
    // 07:59:30 -> 20.5 minutes to 08:20
    const next = nextStopAhead(theTrip, 0, 7 * 3600 + 59 * 60 + 30);
    expect(next!.minutesAway).toBe(20);
  });

  it("reports the day offset for a stop after midnight", () => {
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
          sM: 555,
        }),
      ],
      segments: [segmentGeom({ fromCode: "AAA", toCode: "BBB", lengthM: 555, coordinates: LINE })],
      firstAbs: 85_800,
      lastAbs: 86_400 + 1_800,
    });
    const next = nextStopAhead(overnight, 0, 85_500);
    expect(next!.code).toBe("BBB");
    expect(next!.dayOffset).toBe(1);
    expect(next!.scheduledTime).toBe("00:30");
    // 23:45 -> 00:30 is exactly 45 minutes.
    expect(next!.minutesAway).toBe(45);
  });
});

describe("board times survive a DST-free WIB offset", () => {
  it("agrees with wibToEpochMs for the printed departure", () => {
    const snapshot = snapshotOf([sampleTrip()]);
    const board = stationBoard(snapshot, "AAA", midnight + 7 * 3600 * 1000, DEFAULT_POLICY);
    expect(board[0]!.departsAtMs).toBe(
      wibToEpochMs({ year: 2026, month: 12, day: 1 }, 8 * 3600),
    );
  });
});
