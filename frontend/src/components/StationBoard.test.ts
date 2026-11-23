/**
 * Ordering helpers for the station board.
 */
import { describe, expect, it } from "vitest";
import { boardSortKey, formatBoardTime, isBoardable, nextBoardEntry } from "./StationBoard";
import type { BoardEntry } from "../engine/queries";

function entry(partial: Partial<BoardEntry> & { departsAtMs?: number }): BoardEntry {
  return {
    tripId: "t",
    trainNo: "50",
    name: "Gajayana",
    relation: "GMR-ML",
    serviceClass: "reguler",
    stationCode: "GMR",
    scheduledTime: "08:00",
    dayOffset: 0,
    coarse: false,
    hiddenByDefault: false,
    ...partial,
    departsAtMs: partial.departsAtMs ?? 0,
  };
}

describe("boardSortKey", () => {
  it("sorts by departure instant", () => {
    const earlier = entry({ departsAtMs: 1000 });
    const later = entry({ departsAtMs: 2000 });
    expect(boardSortKey(earlier)).toBeLessThan(boardSortKey(later));
  });

  it("keeps the sort stable for equal instants", () => {
    expect(boardSortKey(entry({ departsAtMs: 5000 }))).toBe(5000);
  });
});

describe("formatBoardTime", () => {
  it("prints HH:MM with a +1 hari marker for the next day", () => {
    expect(formatBoardTime(entry({ scheduledTime: "01:00", dayOffset: 1 }))).toBe("01:00 (+1 hari)");
  });

  it("omits the marker on the same day", () => {
    expect(formatBoardTime(entry({ scheduledTime: "08:20", dayOffset: 0 }))).toBe("08:20");
  });
});

describe("isBoardable", () => {
  it("treats a reguler entry as boardable", () => {
    expect(isBoardable(entry({ serviceClass: "reguler" }))).toBe(true);
  });

  it("treats a fakultatif entry as not boardable by default", () => {
    expect(isBoardable(entry({ serviceClass: "fakultatif" }))).toBe(false);
  });
});

describe("nextBoardEntry", () => {
  it("returns the earliest entry at or after now", () => {
    const entries = [
      entry({ trainNo: "1", departsAtMs: 1000 }),
      entry({ trainNo: "2", departsAtMs: 2000 }),
      entry({ trainNo: "3", departsAtMs: 3000 }),
    ];
    expect(nextBoardEntry(entries, 1500)!.trainNo).toBe("2");
    expect(nextBoardEntry(entries, 999)!.trainNo).toBe("1");
  });

  it("returns null when everything has gone", () => {
    expect(nextBoardEntry([entry({ departsAtMs: 1000 })], 2000)).toBeNull();
  });

  it("returns null for an empty board", () => {
    expect(nextBoardEntry([], 0)).toBeNull();
  });
});