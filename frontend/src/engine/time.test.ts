/**
 * WIB time arithmetic — fixed UTC+7, no `Intl`, no host time zone.
 *
 * The engine must behave identically in a browser in Jakarta, in a CI container
 * on UTC and in Node on a laptop. `Intl` and `Date` local-time getters both
 * depend on the host configuration, so this module derives the civil date from
 * the epoch millisecond count arithmetically.
 *
 * Reference instants below were computed with Python's `datetime` + a +07:00
 * offset, i.e. the same values `engine/position.py` sees.
 */
import { describe, expect, it } from "vitest";
import {
  addDays,
  civilFromDays,
  formatSod,
  formatSodHm,
  midnightEpochMs,
  wibFromEpochMs,
  wibToEpochMs,
} from "./time";

describe("wibFromEpochMs", () => {
  it("maps 2026-11-30T17:00:00Z to WIB midnight", () => {
    expect(wibFromEpochMs(1796058000000)).toEqual({
      date: { year: 2026, month: 12, day: 1 },
      secondsOfDay: 0,
    });
  });

  it("stays on the previous day one second before WIB midnight", () => {
    expect(wibFromEpochMs(1796057999000)).toEqual({
      date: { year: 2026, month: 11, day: 30 },
      secondsOfDay: 86_399,
    });
  });

  it("carries a fractional second without losing it", () => {
    const parts = wibFromEpochMs(1795971599500);
    expect(parts.date).toEqual({ year: 2026, month: 11, day: 29 });
    expect(parts.secondsOfDay).toBeCloseTo(86_399.5, 6);
  });

  it("handles the 00:00:30 edge used by the midnight-tail tests", () => {
    expect(wibFromEpochMs(1796058030000)).toEqual({
      date: { year: 2026, month: 12, day: 1 },
      secondsOfDay: 30,
    });
  });
});

describe("wibToEpochMs", () => {
  it("round-trips with wibFromEpochMs", () => {
    for (const ms of [1796058000000, 1796057999000, 1803834000000]) {
      const parts = wibFromEpochMs(ms);
      expect(wibToEpochMs(parts.date, parts.secondsOfDay)).toBe(ms);
    }
  });

  it("treats WIB as exactly UTC+7", () => {
    expect(wibToEpochMs({ year: 2026, month: 12, day: 1 }, 0)).toBe(1796058000000);
  });
});

describe("civilFromDays", () => {
  it("converts the Unix epoch and known dates", () => {
    expect(civilFromDays(0)).toEqual({ year: 1970, month: 1, day: 1 });
    expect(civilFromDays(20_788)).toEqual({ year: 2026, month: 12, day: 1 });
    expect(civilFromDays(20_878)).toEqual({ year: 2027, month: 3, day: 1 });
  });

  it("handles a leap day", () => {
    // 2028-02-29 is day 21243; the day before is 2028-02-28.
    expect(civilFromDays(21_242)).toEqual({ year: 2028, month: 2, day: 28 });
    expect(civilFromDays(21_243)).toEqual({ year: 2028, month: 2, day: 29 });
    expect(civilFromDays(21_244)).toEqual({ year: 2028, month: 3, day: 1 });
  });
});

describe("addDays", () => {
  it("crosses a month and a year boundary", () => {
    expect(addDays({ year: 2026, month: 12, day: 1 }, -1)).toEqual({
      year: 2026,
      month: 11,
      day: 30,
    });
    expect(addDays({ year: 2027, month: 1, day: 1 }, -1)).toEqual({
      year: 2026,
      month: 12,
      day: 31,
    });
  });

  it("is its own inverse for the offsets the engine scans", () => {
    const start = { year: 2026, month: 12, day: 1 };
    for (const k of [0, 1, 2]) {
      expect(addDays(addDays(start, -k), k)).toEqual(start);
    }
  });
});

describe("midnightEpochMs", () => {
  it("is WIB midnight of the service date", () => {
    expect(midnightEpochMs({ year: 2026, month: 12, day: 1 })).toBe(1796058000000);
  });
});

describe("formatSod", () => {
  it("prints HH:MM:SS with zero padding", () => {
    expect(formatSod(0)).toBe("00:00:00");
    expect(formatSod(300)).toBe("00:05:00");
    expect(formatSod(86_399)).toBe("23:59:59");
    expect(formatSod(3_661)).toBe("01:01:01");
  });

  it("truncates a fractional second rather than rounding it", () => {
    expect(formatSod(59.9)).toBe("00:00:59");
  });
});

describe("formatSodHm", () => {
  it("prints HH:MM for the status pill", () => {
    expect(formatSodHm(0)).toBe("00:00");
    expect(formatSodHm(7 * 3600 + 5 * 60 + 42)).toBe("07:05");
  });
});
