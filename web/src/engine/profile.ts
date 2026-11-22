// trapezoid_v1 (ADR 004) ported from engine/profile.py.
// PURE: no I/O, no clock, no randomness.

export interface Leg {
  tI: number;
  tJ: number;
  sI: number;
  sJ: number;
  easeStartS: number;
  easeEndS: number;
  cruiseMps: number;
}

export function buildLeg(
  tI: number,
  tJ: number,
  sI: number,
  sJ: number,
  easeStart: boolean,
  easeEnd: boolean,
  accelTimeS: number,
): Leg | null {
  const duration = tJ - tI;
  const length = sJ - sI;
  if (duration <= 0 || length <= 0) return null;

  let easeS = easeStart ? Math.min(accelTimeS, duration / 3) : 0;
  let easeE = easeEnd ? Math.min(accelTimeS, duration / 3) : 0;

  if (easeS + easeE >= duration) {
    const scale = (duration / (easeS + easeE + 1e-9)) * 0.99;
    easeS *= scale;
    easeE *= scale;
  }

  const cruiseTime = duration - easeS / 2 - easeE / 2;
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

export function distanceAt(leg: Leg, t: number): number {
  if (t <= leg.tI) return leg.sI;
  if (t >= leg.tJ) return leg.sJ;

  const v = leg.cruiseMps;
  const dt = t - leg.tI;
  const duration = leg.tJ - leg.tI;
  const aS = leg.easeStartS;
  const aE = leg.easeEndS;

  if (aS > 0 && dt < aS) {
    const accel = v / aS;
    return leg.sI + 0.5 * accel * dt * dt;
  }

  const cruiseStart = aS;
  const cruiseEnd = duration - aE;
  if (dt <= cruiseEnd) {
    return leg.sI + 0.5 * v * aS + v * (dt - cruiseStart);
  }

  const remaining = leg.tJ - t;
  const decel = aE > 0 ? v / aE : 0;
  return leg.sJ - 0.5 * decel * remaining * remaining;
}

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
