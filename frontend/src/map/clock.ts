/**
 * The simulation clock: a pure state machine.
 *
 * `Live` tracks `Date.now()`; `Simulasi` pins one instant that the scrubber,
 * the nudges and the play-speed advance from. The engine only ever sees an
 * instant, so switching modes changes nothing downstream.
 */
import { midnightEpochMs, wibFromEpochMs } from "../engine/time";

export type ClockMode = "live" | "sim";
export type ReplaySpeed = 1 | 5 | 15 | 60;
export const REPLAY_SPEEDS: readonly ReplaySpeed[] = [1, 5, 15, 60];

export interface ClockState {
  readonly mode: ClockMode;
  /** epoch milliseconds */
  readonly instant: number;
  readonly speed: ReplaySpeed;
  readonly playing: boolean;
}

const DAY_MS = 86_400_000;

export function liveInstant(now: number, speed: ReplaySpeed = 1): ClockState {
  return { mode: "live", instant: now, speed, playing: true };
}

export function simClock(instant: number, speed: ReplaySpeed = 1, playing = false): ClockState {
  return { mode: "sim", instant, speed, playing };
}

export function isLive(clock: ClockState): boolean {
  return clock.mode === "live";
}

/** Pin the current instant as a simulation. */
export function toSimInstant(clock: ClockState): ClockState {
  return { mode: "sim", instant: clock.instant, speed: clock.speed, playing: clock.playing };
}

/**
 * Move the instant to `hour:minute` on the SAME WIB calendar day the clock is
 * currently showing. A scrub is a within-day gesture, never a day change.
 */
export function scrubTo(clock: ClockState, hour: number, minute: number): ClockState {
  const day = wibFromEpochMs(clock.instant).date;
  const midnight = midnightEpochMs(day);
  const within = ((hour * 60 + minute) % (24 * 60)) * 60 * 1000;
  return { mode: "sim", instant: midnight + within, speed: clock.speed, playing: clock.playing };
}

/**
 * The instant `minutesOfDay` into a day that is `daysFromReference` days after
 * the Unix epoch. An absolute anchor keeps this free of the clock's current day,
 * which is what makes it testable.
 */
export function scrubWithinDay(daysFromReference: number, minutesOfDay: number): number {
  const referenceMidnight = midnightEpochMs({ year: 1970, month: 1, day: 1 });
  const within = ((minutesOfDay % (24 * 60)) + 24 * 60) % (24 * 60);
  return referenceMidnight + daysFromReference * DAY_MS + within * 60 * 1000;
}

/** Move by whole minutes. A nudge from Live pins Live's current instant first. */
export function nudge(clock: ClockState, minutes: number): ClockState {
  const pinned = clock.mode === "live" ? toSimInstant(clock) : clock;
  return { ...pinned, instant: pinned.instant + minutes * 60 * 1000 };
}

/**
 * Advance by the elapsed wall time. A live clock is always the wall clock; a
 * paused simulation does not move.
 */
export function advance(clock: ClockState, elapsedMs: number, now: number): ClockState {
  if (clock.mode === "live") return { ...clock, instant: now };
  if (!clock.playing) return clock;
  if (elapsedMs <= 0) return clock;
  return { ...clock, instant: clock.instant + elapsedMs * clock.speed };
}

export function withSpeed(clock: ClockState, speed: ReplaySpeed): ClockState {
  return { ...clock, speed };
}

export function withPlaying(clock: ClockState, playing: boolean): ClockState {
  return { ...clock, playing };
}

export function backToLive(clock: ClockState, now: number): ClockState {
  return liveInstant(now, clock.speed);
}
