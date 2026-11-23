/**
 * Schedule-version helpers.
 *
 * `engine/position.py` declares `enforce_effective_from` but never reads it, so
 * the gate lives here rather than in `positionsAt` — putting it in the engine
 * would make the port disagree with its reference. The UI uses this to decide
 * what to say about the schedule version, not to hide trains.
 *
 * ADR 002 amendment (2026-11-23): the frontend shows no preview banner. The
 * estimate status is always on screen in the status pill, and the full text,
 * effective date and hash live in the "Tentang" modal.
 */
import { compareDates, parseIsoDate, type CivilDate } from "./time";

export type SchedulePhase = "preview" | "active" | "expired";

export interface ScheduleStatus {
  readonly phase: SchedulePhase;
  readonly effectiveFrom: string;
  readonly effectiveTo: string | null;
  readonly contentHash: string;
}

/** Where `today` sits relative to the schedule's validity window. */
export function scheduleStatus(
  effectiveFrom: string,
  effectiveTo: string | null,
  today: CivilDate,
  contentHash: string,
): ScheduleStatus {
  const from = parseIsoDate(effectiveFrom);
  if (compareDates(today, from) < 0) {
    return { phase: "preview", effectiveFrom, effectiveTo, contentHash };
  }
  if (effectiveTo !== null && compareDates(today, parseIsoDate(effectiveTo)) > 0) {
    return { phase: "expired", effectiveFrom, effectiveTo, contentHash };
  }
  return { phase: "active", effectiveFrom, effectiveTo, contentHash };
}

/**
 * Whether the schedule may be presented as in force.
 *
 * Mirrors `Policy.enforce_effective_from`: when the flag is off (the development
 * default) a preview schedule is still usable; when it is on, a preview schedule
 * must not be presented as current.
 */
export function isScheduleActive(
  effectiveFrom: string,
  today: CivilDate,
  enforceEffectiveFrom: boolean,
): boolean {
  if (!enforceEffectiveFrom) return true;
  return compareDates(today, parseIsoDate(effectiveFrom)) >= 0;
}

/**
 * The top-right status pill text: `Live (Estimasi) · HH:MM WIB`.
 *
 * The word "Estimasi" is load-bearing (Hard Rule 6, ADR 002 amendment): it is
 * what tells a user this is not a live position, now that the banner and the
 * footer bar are gone.
 */
export function statusPillLabel(secondsOfDay: number): string {
  const whole = Math.trunc(secondsOfDay);
  const hours = String(Math.floor(whole / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((whole % 3600) / 60)).padStart(2, "0");
  return `Live (Estimasi) · ${hours}:${minutes} WIB`;
}
