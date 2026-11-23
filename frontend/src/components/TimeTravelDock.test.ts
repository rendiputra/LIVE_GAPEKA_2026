/**
 * Formatting helpers for the time-travel dock.
 */
import { describe, expect, it } from "vitest";
import {
  dateLabel,
  formatDockTime,
  nudgeMinutes,
  scrubMinutes,
  simLabel,
} from "./TimeTravelDock";
import { midnightEpochMs } from "../engine/time";

const MIDNIGHT = midnightEpochMs({ year: 2026, month: 12, day: 1 });

describe("formatDockTime", () => {
  it("prints HH:MM WIB in tabular numerals", () => {
    expect(formatDockTime(MIDNIGHT + (7 * 3600 + 5 * 60) * 1000)).toBe("07:05 WIB");
  });

  it("prints midnight as 00:00", () => {
    expect(formatDockTime(MIDNIGHT)).toBe("00:00 WIB");
  });

  it("prints the last minute of the day", () => {
    expect(formatDockTime(MIDNIGHT + (23 * 3600 + 59 * 60) * 1000)).toBe("23:59 WIB");
  });
});

describe("dateLabel", () => {
  it("prints a short Indonesian date", () => {
    expect(dateLabel(MIDNIGHT)).toBe("1 Des 2026");
  });

  it("prints the following day across midnight", () => {
    expect(dateLabel(MIDNIGHT + 86_400_000)).toBe("2 Des 2026");
  });
});

describe("simLabel", () => {
  it("prefixes Simulasi", () => {
    expect(simLabel(MIDNIGHT)).toBe("Simulasi (Estimasi) · 00:00 WIB");
  });
});

describe("scrubMinutes", () => {
  it("maps a slider value to minutes of the day", () => {
    expect(scrubMinutes(0)).toBe(0);
    expect(scrubMinutes(720)).toBe(12 * 60);
    expect(scrubMinutes(1440)).toBe(0);
  });
});

describe("nudgeMinutes", () => {
  it("steps by fifteen minutes", () => {
    expect(nudgeMinutes(-15)).toBe(-15);
    expect(nudgeMinutes(15)).toBe(15);
  });
});