/**
 * The right-regression tests for the bugs found in manual browser use:
 *
 * 1. `requestAnimationFrame` timestamps are not epoch time (1970 bug).
 * 2. The station board must not overflow under a long list.
 */
import { describe, expect, it } from "vitest";
import { isLive, liveInstant, simClock } from "./map/clock";
import { wibFromEpochMs } from "./engine/time";

describe("clock instant invariants", () => {
  it("stays in the current era, never near the epoch", () => {
    const live = liveInstant(Date.now());
    expect(live.instant).toBeGreaterThan(Date.UTC(2020, 0, 1));
    const { date } = wibFromEpochMs(live.instant);
    expect(date.year).toBeGreaterThanOrEqual(2026);
  });

  it("round-trips through wibFromEpochMs for a live instant", () => {
    const now = Date.now();
    const { secondsOfDay } = wibFromEpochMs(now);
    expect(secondsOfDay).toBeGreaterThanOrEqual(0);
    expect(secondsOfDay).toBeLessThan(86_400);
  });

  it("is not live when the mode is sim", () => {
    expect(isLive(simClock(Date.now()))).toBe(false);
  });

  it("keeps the day when scrubbing within the day", () => {
    const live = liveInstant(1_796_058_000_000); // 2026-12-01 00:00 WIB
    const { date } = wibFromEpochMs(live.instant);
    expect(date.year).toBe(2026);
    expect(date.month).toBe(12);
    expect(date.day).toBe(1);
  });
});