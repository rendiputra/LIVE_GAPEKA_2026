/**
 * Search across trains and stations.
 *
 * Grouped results (Kereta Api / Stasiun), capped so a common substring does not
 * flood the list. Stations without a coordinate are still searchable — the row
 * simply offers the station board instead of a map pan.
 */
import { describe, expect, it } from "vitest";
import { search, topSuggestions } from "./SearchPanel";
import type { ScheduleSnapshot, Trip } from "../engine/types";

function snapshotOf(trips: readonly Trip[]) {
  const stations = new Map([
    ["GMR", { code: "GMR", officialName: "Gambir", disambiguator: null, lat: -6.176, lon: 106.830 }],
    ["PK", { code: "PK", officialName: "Pekalongan", disambiguator: null, lat: -6.888, lon: 109.676 }],
    ["CIK", { code: "CIK", officialName: "Cikampek", disambiguator: null, lat: null, lon: null }],
  ]);
  return {
    versionName: "Gapeka 2026",
    effectiveFrom: "2026-12-01",
    effectiveTo: null,
    contentHash: "x",
    maxDayOffset: 1,
    policy: {} as never,
    trips,
    stations,
    attribution: { osm: "", osm_url: "", disclaimer: "" },
  } as unknown as ScheduleSnapshot;
}

function trip(tripId: string, trainNo: string, name: string): Trip {
  return {
    tripId,
    trainNo,
    name,
    relation: "",
    book: 1,
    serviceClass: "reguler",
    geometryStatus: "complete",
    hasUntimedMarkers: false,
    hasBypassedWaypoints: false,
    hasStraightLineSegment: false,
    waypoints: [],
    rows: [],
    segments: [],
    firstAbs: 0,
    lastAbs: 0,
    totalLengthM: 0,
    hiddenByDefault: false,
  };
}

const snapshot = snapshotOf([
  trip("t1", "50", "Gajayana"),
  trip("t2", "249", "Kaligung"),
  trip("t3", "260F", "Banyubiru"),
]);

describe("search", () => {
  it("matches a train number", () => {
    const results = search(snapshot, "249");
    expect(results.trains.map((entry) => entry.trainNo)).toContain("249");
  });

  it("matches a train name, case-insensitively", () => {
    expect(search(snapshot, "gajayana").trains.map((entry) => entry.trainNo)).toContain("50");
    expect(search(snapshot, "GAJAYANA").trains).toHaveLength(1);
  });

  it("matches a station name", () => {
    const results = search(snapshot, "pekalongan");
    expect(results.stations.map((entry) => entry.code)).toContain("PK");
  });

  it("matches a station code exactly", () => {
    expect(search(snapshot, "GMR").stations.map((entry) => entry.code)).toContain("GMR");
  });

  it("returns both groups", () => {
    const results = search(snapshot, "a");
    expect(results.trains.length).toBeGreaterThan(0);
    expect(results.stations.length).toBeGreaterThan(0);
  });

  it("returns nothing for a query with no matches", () => {
    const results = search(snapshot, "zzzqqq-no-such-place");
    expect(results.trains).toHaveLength(0);
    expect(results.stations).toHaveLength(0);
  });

  it("ignores leading and trailing whitespace", () => {
    expect(search(snapshot, "  50  ").trains.map((entry) => entry.trainNo)).toContain("50");
  });

  it("still finds a station without a coordinate", () => {
    const results = search(snapshot, "cikampek");
    expect(results.stations).toHaveLength(1);
    expect(results.stations[0]!.code).toBe("CIK");
    expect(results.stations[0]!.located).toBe(false);
  });

  it("caps the number of results", () => {
    const many = Array.from({ length: 30 }, (_, index) =>
      trip(`t${index}`, String(1000 + index), `Searchable ${index}`),
    );
    const results = search(snapshotOf(many), "searchable");
    expect(results.trains.length).toBeLessThanOrEqual(8);
  });

  it("requires a minimum query length", () => {
    expect(search(snapshot, "").trains).toHaveLength(0);
    expect(search(snapshot, "a").trains.length).toBeGreaterThan(0);
  });
});

describe("topSuggestions", () => {
  it("suggests the empty-query shortlist", () => {
    expect(topSuggestions(snapshot, 3).length).toBeGreaterThan(0);
  });
});