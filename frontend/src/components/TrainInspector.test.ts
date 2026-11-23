/**
 * Inspector formatting helpers.
 */
import { describe, expect, it } from "vitest";
import {
  currentIndex,
  formatEta,
  formatSpeed,
  formatStopTime,
  progressPercent,
  statusLabel,
  stopBadge,
} from "./TrainInspector";
import { segmentGeom, trip, waypoint } from "../engine/testUtils";
import { midnightEpochMs } from "../engine/time";

const LINE = [
  { lat: -6.2, lon: 106.8 },
  { lat: -6.21, lon: 106.8 },
];

function sampleTrip() {
  return trip({
    tripId: "t",
    trainNo: "50",
    name: "Gajayana",
    relation: "GMR-ML",
    waypoints: [
      waypoint({ seq: 0, stationCode: "GMR", arriveSod: 28_800, departSod: 28_800, sM: 0 }),
      waypoint({ seq: 1, stationCode: "MRI", arriveSod: 30_000, departSod: 30_000, sM: 555 }),
      waypoint({ seq: 2, stationCode: "ML", arriveSod: 31_200, departSod: 31_200, sM: 1111.95 }),
    ],
    segments: [
      segmentGeom({ fromCode: "GMR", toCode: "MRI", lengthM: 555, coordinates: LINE }),
      segmentGeom({ fromCode: "MRI", toCode: "ML", lengthM: 556.95, coordinates: LINE }),
    ],
    firstAbs: 28_800,
    lastAbs: 31_200,
    totalLengthM: 1111.95,
  });
}

describe("formatStopTime", () => {
  it("prints HH:MM when the seconds are zero", () => {
    expect(formatStopTime(23 * 3600 + 35 * 60, 0)).toBe("23:35 WIB");
  });

  it("prints the seconds when they are non-zero", () => {
    expect(formatStopTime(23 * 3600 + 35 * 60 + 7, 0)).toBe("23:35:07 WIB");
  });

  it("adds a +1 hari marker for the next day", () => {
    expect(formatStopTime(30 * 60, 1)).toBe("00:30 WIB (+1 hari)");
  });

  it("omits the marker on the same day", () => {
    expect(formatStopTime(30 * 60, 0)).not.toContain("hari");
  });
});

describe("formatEta", () => {
  it("says sekarang for zero or negative minutes", () => {
    expect(formatEta(0)).toBe("sekarang");
    expect(formatEta(-5)).toBe("sekarang");
  });

  it("prints minutes below an hour", () => {
    expect(formatEta(12)).toBe("±12 mnt");
  });

  it("prints hours for longer ETAs", () => {
    expect(formatEta(60)).toBe("1 jam");
    expect(formatEta(95)).toBe("1 jam 35 mnt");
  });

  it("never rounds up", () => {
    expect(formatEta(59)).toBe("±59 mnt");
  });
});

describe("formatSpeed", () => {
  it("rounds to whole kilometres per hour", () => {
    expect(formatSpeed(84.4)).toBe("84 km/jam");
    expect(formatSpeed(0)).toBe("0 km/jam");
  });
});

describe("progressPercent", () => {
  it("maps distance to a percentage", () => {
    expect(progressPercent(555, 1111.95)).toBeCloseTo(49.9, 0);
    expect(progressPercent(0, 0)).toBe(0);
  });

  it("clamps both ends", () => {
    expect(progressPercent(-10, 100)).toBe(0);
    expect(progressPercent(200, 100)).toBe(100);
  });
});

describe("statusLabel", () => {
  it("uses the familiar English terms", () => {
    expect(statusLabel("running")).toBe("Running");
    expect(statusLabel("at_station")).toBe("At Station");
  });
});

describe("stopBadge", () => {
  it("labels each row type", () => {
    expect(stopBadge("stop")).toBe("Stop");
    expect(stopBadge("pass")).toBe("Pass");
    expect(stopBadge("unknown_untimed")).toBe("Untimed");
  });
});

describe("currentIndex", () => {
  const theTrip = sampleTrip();

  it("returns the first row not yet departed", () => {
    // 08:10 -> still heading to MRI (next row index 1)
    expect(currentIndex(theTrip, 29_400)).toBe(1);
    // 08:30 -> heading to ML
    expect(currentIndex(theTrip, 30_600)).toBe(2);
  });

  it("returns the last row when the trip is over", () => {
    expect(currentIndex(theTrip, 32_000)).toBe(2);
  });
});

describe("midnight arithmetic used by the inspector", () => {
  it("is anchored on WIB midnight", () => {
    expect(midnightEpochMs({ year: 2026, month: 12, day: 1 })).toBe(1796058000000);
  });
});