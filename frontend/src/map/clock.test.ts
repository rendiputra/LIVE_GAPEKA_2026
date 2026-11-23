/**
 * The simulation clock.
 *
 * `Live` means the instant is `Date.now()` reinterpreted in WIB and advanced
 * only by the passage of time. Switching to `Simulasi` pins one instant; the
 * 24 h scrubber and the −15 m / +15 m nudges move from there, and the engine
 * simply evaluates at the new instant. Nothing else changes.
 *
 * All of this is pure arithmetic: the loop that advances it lives in `loop.ts`.
 */
import { describe, expect, it } from "vitest";
import {
  advance,
  isLive,
  liveInstant,
  nudge,
  scrubWithinDay,
  scrubTo,
  simClock,
  toSimInstant,
  withPlaying,
} from "./clock";
import { midnightEpochMs } from "../engine/time";

const MIDNIGHT = midnightEpochMs({ year: 2026, month: 12, day: 1 });

describe("live clock", () => {
  it("starts live at the real instant", () => {
    const clock = liveInstant(1234567890123);
    expect(clock.mode).toBe("live");
    expect(clock.instant).toBe(1234567890123);
    expect(clock.speed).toBe(1);
  });

  it("is live by default", () => {
    expect(isLive(liveInstant(1))).toBe(true);
    expect(isLive(simClock(1))).toBe(false);
  });
});

describe("switching to Simulasi", () => {
  it("pins the current live instant when the user scrubs", () => {
    const live = liveInstant(MIDNIGHT + 8 * 3600 * 1000);
    const sim = scrubTo(live, 10, 0);
    expect(sim.mode).toBe("sim");
    expect(sim.instant).toBe(MIDNIGHT + 10 * 3600 * 1000);
  });

  it("keeps the same calendar day when scrubbing forward", () => {
    const live = liveInstant(MIDNIGHT + 8 * 3600 * 1000);
    const sim = scrubTo(live, 23, 59);
    expect(sim.instant).toBe(MIDNIGHT + (23 * 3600 + 59 * 60) * 1000);
  });

  it("keeps the same calendar day when scrubbing backward", () => {
    const live = liveInstant(MIDNIGHT + 8 * 3600 * 1000);
    const sim = scrubTo(live, 0, 30);
    expect(sim.instant).toBe(MIDNIGHT + 30 * 60 * 1000);
  });
});

describe("nudges", () => {
  it("moves −15 m and +15 m", () => {
    const live = liveInstant(MIDNIGHT + 8 * 3600 * 1000);
    expect(nudge(live, -15).instant).toBe(MIDNIGHT + (8 * 3600 - 900) * 1000);
    expect(nudge(live, 15).instant).toBe(MIDNIGHT + (8 * 3600 + 900) * 1000);
  });

  it("switches to Simulasi when nudging from Live", () => {
    const live = liveInstant(MIDNIGHT + 8 * 3600 * 1000);
    expect(nudge(live, 15).mode).toBe("sim");
  });

  it("can cross midnight", () => {
    const live = liveInstant(MIDNIGHT + 23 * 3600 * 1000 + 50 * 60 * 1000);
    const forward = nudge(live, 15);
    expect(forward.instant - MIDNIGHT).toBe(86_700 * 1000);
  });
});

describe("advance", () => {
  it("does not move a paused clock", () => {
    const sim = simClock(MIDNIGHT + 1000, 5);
    expect(advance(sim, 0, 5000).instant).toBe(MIDNIGHT + 1000);
  });

  it("advances by speed while playing", () => {
    const sim = withPlaying(simClock(MIDNIGHT + 1000, 5), true);
    // 2 ms of wall time at 5x = 10 ms of scheduled time.
    expect(advance(sim, 2, 5000).instant).toBe(MIDNIGHT + 1010);
  });

  it("keeps a live clock at the wall clock", () => {
    const live = liveInstant(12345);
    expect(advance(live, 999, 7000).instant).toBe(7000);
  });
});

describe("scrubWithinDay", () => {
  // 2026-12-01 is day 20788 since the epoch.
  it("maps a slider value onto a day anchored by its epoch day index", () => {
    expect(scrubWithinDay(20_788, 6 * 60 + 30)).toBe(MIDNIGHT + (6 * 3600 + 1800) * 1000);
  });

  it("wraps 24:00 back to the start of the day", () => {
    expect(scrubWithinDay(20_788, 24 * 60)).toBe(MIDNIGHT);
  });

  it("wraps a negative value forward", () => {
    expect(scrubWithinDay(20_788, -30)).toBe(MIDNIGHT + (23 * 3600 + 30 * 60) * 1000);
  });
});

describe("toSimInstant", () => {
  it("converts a live clock into a sim clock at the same instant", () => {
    const live = liveInstant(MIDNIGHT + 8 * 3600 * 1000);
    const sim = toSimInstant(live);
    expect(sim.mode).toBe("sim");
    expect(sim.instant).toBe(live.instant);
  });
});
