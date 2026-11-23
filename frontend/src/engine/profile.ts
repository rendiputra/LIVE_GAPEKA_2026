/**
 * Trapezoidal motion profile — the TypeScript port of `engine/profile.py`
 * (ADR 004). PURE: no I/O, no clock, no randomness.
 *
 * Between two consecutive TIMED waypoints i -> j:
 *
 * - `D = Tj - Ti` seconds, `L = Sj - Si` metres;
 * - an end gets an acceleration/deceleration phase ONLY if that row is a `stop`
 *   (a train at rest). A `pass` row gets none;
 * - `a_s = min(accelTimeS, D/3)` at an eased start, `a_e` likewise at an eased end;
 * - cruise speed `v = L / (D - a_s/2 - a_e/2)`;
 * - the position is piecewise quadratic (accelerating), linear (cruising), then
 *   quadratic (decelerating), and reaches exactly `Sj` at `Tj`.
 *
 * This is an ASSUMPTION about how trains move, not something the Gapeka states.
 * The arithmetic is deliberately written in the same order as the Python source
 * so the two produce identical doubles.
 */

/** Default easing duration; mirrors `Policy.accel_time_s`. */
export const DEFAULT_ACCEL_TIME_S = 60;

export interface Leg {
  /** seconds, absolute since service-date midnight */
  readonly tI: number;
  readonly tJ: number;
  /** metres along the trip polyline */
  readonly sI: number;
  readonly sJ: number;
  readonly easeStartS: number;
  readonly easeEndS: number;
  readonly cruiseMps: number;
}

export interface LegInput {
  readonly tI: number;
  readonly tJ: number;
  readonly sI: number;
  readonly sJ: number;
  readonly easeStart: boolean;
  readonly easeEnd: boolean;
  readonly accelTimeS?: number;
}

export function legDuration(leg: Leg): number {
  return leg.tJ - leg.tI;
}

export function legLength(leg: Leg): number {
  return leg.sJ - leg.sI;
}

/** Build a leg, or `null` when it is degenerate (no time or no distance). */
export function buildLeg(input: LegInput): Leg | null {
  const { tI, tJ, sI, sJ, easeStart, easeEnd } = input;
  const accelTimeS = input.accelTimeS ?? DEFAULT_ACCEL_TIME_S;

  const duration = tJ - tI;
  const length = sJ - sI;
  if (duration <= 0 || length <= 0) return null;

  // A leg may not spend more than a third of its time easing at each end.
  let easeS = easeStart ? Math.min(accelTimeS, duration / 3.0) : 0;
  let easeE = easeEnd ? Math.min(accelTimeS, duration / 3.0) : 0;

  // Guard: the eased portions must leave a positive cruise interval.
  if (easeS + easeE >= duration) {
    const scale = (duration / (easeS + easeE + 1e-9)) * 0.99;
    easeS *= scale;
    easeE *= scale;
  }

  const cruiseTime = duration - easeS / 2.0 - easeE / 2.0;
  if (cruiseTime <= 0) return null;

  return {
    tI,
    tJ,
    sI,
    sJ,
    easeStartS: easeS,
    easeEndS: easeE,
    cruiseMps: length / cruiseTime,
  };
}

/** Distance along the leg at absolute time `t` (clamped to the leg). */
export function distanceAt(leg: Leg, t: number): number {
  if (t <= leg.tI) return leg.sI;
  if (t >= leg.tJ) return leg.sJ;

  const v = leg.cruiseMps;
  const dt = t - leg.tI;
  const duration = leg.tJ - leg.tI;
  const aS = leg.easeStartS;
  const aE = leg.easeEndS;

  if (aS > 0 && dt < aS) {
    // Quadratic acceleration from rest.
    const accel = v / aS;
    return leg.sI + 0.5 * accel * dt * dt;
  }

  const cruiseStart = aS;
  const cruiseEnd = duration - aE;
  if (dt <= cruiseEnd) {
    return leg.sI + 0.5 * v * aS + v * (dt - cruiseStart);
  }

  // Quadratic deceleration to rest at sJ.
  const remaining = leg.tJ - t;
  const decel = aE > 0 ? v / aE : 0;
  return leg.sJ - 0.5 * decel * remaining * remaining;
}

/** Speed in m/s at absolute time `t` (0 at an eased end). */
export function speedAt(leg: Leg, t: number): number {
  if (t <= leg.tI || t >= leg.tJ) return 0;
  const v = leg.cruiseMps;
  const aS = leg.easeStartS;
  const aE = leg.easeEndS;
  const dt = t - leg.tI;
  const remaining = leg.tJ - t;

  if (aS > 0 && dt < aS) return (v / aS) * dt;
  if (aE > 0 && remaining < aE) return (v / aE) * remaining;
  return v;
}
