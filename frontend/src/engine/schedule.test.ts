/**
 * Schedule-version and status-pill behaviour.
 *
 * The effective-date gate lives here, NOT in `positionsAt`: the Python reference
 * declares `enforce_effective_from` and never reads it, so gating inside the
 * engine would make the port disagree with its own fixture.
 */
import { describe, expect, it } from "vitest";
import { isScheduleActive, scheduleStatus, statusPillLabel } from "./schedule";

const TODAY = { year: 2026, month: 11, day: 23 } as const;
const EFFECTIVE = "2026-12-01";
const HASH = "2f8588adc0168c0e";

describe("scheduleStatus", () => {
  it("reports preview before the effective date", () => {
    const status = scheduleStatus(EFFECTIVE, null, TODAY, HASH);
    expect(status.phase).toBe("preview");
    expect(status.effectiveFrom).toBe(EFFECTIVE);
    expect(status.effectiveTo).toBeNull();
    expect(status.contentHash).toBe(HASH);
  });

  it("reports active on the effective date itself", () => {
    expect(
      scheduleStatus(EFFECTIVE, null, { year: 2026, month: 12, day: 1 }, HASH).phase,
    ).toBe("active");
  });

  it("reports active after the effective date", () => {
    expect(
      scheduleStatus(EFFECTIVE, null, { year: 2027, month: 3, day: 1 }, HASH).phase,
    ).toBe("active");
  });

  it("reports expired past a stated effective_to", () => {
    expect(
      scheduleStatus(EFFECTIVE, "2027-05-31", { year: 2027, month: 6, day: 1 }, HASH).phase,
    ).toBe("expired");
    expect(
      scheduleStatus(EFFECTIVE, "2027-05-31", { year: 2027, month: 5, day: 31 }, HASH).phase,
    ).toBe("active");
  });
});

describe("isScheduleActive", () => {
  it("allows a preview schedule while enforcement is off (the development default)", () => {
    expect(isScheduleActive(EFFECTIVE, TODAY, false)).toBe(true);
  });

  it("refuses a preview schedule when enforcement is on", () => {
    expect(isScheduleActive(EFFECTIVE, TODAY, true)).toBe(false);
  });

  it("allows an in-force schedule even when enforcement is on", () => {
    expect(isScheduleActive(EFFECTIVE, { year: 2026, month: 12, day: 1 }, true)).toBe(true);
  });
});

describe("statusPillLabel", () => {
  it("states the estimate status and the WIB time", () => {
    expect(statusPillLabel(7 * 3600 + 5 * 60 + 42)).toBe("Live (Estimasi) · 07:05 WIB");
  });

  it("zero-pads both fields", () => {
    expect(statusPillLabel(0)).toBe("Live (Estimasi) · 00:00 WIB");
    expect(statusPillLabel(59)).toBe("Live (Estimasi) · 00:00 WIB");
  });

  it("never prints a UTC time (a 23:59 WIB instant stays 23:59)", () => {
    expect(statusPillLabel(23 * 3600 + 59 * 60)).toBe("Live (Estimasi) · 23:59 WIB");
  });

  it("always contains the word Estimasi (Hard Rule 6 amendment)", () => {
    for (const second of [0, 3600, 43_200, 86_399]) {
      expect(statusPillLabel(second)).toContain("Estimasi");
    }
  });
});
