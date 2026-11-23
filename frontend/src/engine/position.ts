/**
 * Pure position estimation — the TypeScript port of `engine/position.py`.
 *
 * PURE by contract: input is a snapshot, an epoch instant and an explicit
 * policy. No database, no network, no system clock, no randomness, no `Intl`.
 *
 * Time model (E2): every Java station is WIB. Schedule times are seconds from
 * the start of the SERVICE DATE, plus `86400 * dayOffset`. For a query instant
 * the engine scans service dates `wibDate(instant) - k` for `k in 0..maxDayOffset`,
 * so a trip that started "yesterday" still appears after midnight (e.g. KA 260F).
 *
 * `enforce_effective_from` is deliberately NOT applied here: `engine/position.py`
 * declares it and never reads it, so gating inside the engine would make the port
 * disagree with its reference. The effective-date gate lives in `isScheduleActive`
 * (see `queries.ts`) and is applied by the UI.
 */
import { bearing, pointAt } from "./geometry";
import { buildLeg, distanceAt, type Leg, speedAt } from "./profile";
import { formatSod, wibFromEpochMs } from "./time";
import {
  arriveAbs,
  departAbs,
  isShownByClass,
  isVisible,
  MOTION_MODEL,
  type Policy,
  SECONDS_PER_DAY,
  type ScheduleSnapshot,
  type SegmentGeom,
  STATUS_AT_STATION,
  STATUS_RUNNING,
  type TrainPosition,
  type TrainStatus,
  type Trip,
  type Waypoint,
} from "./types";

interface TimedLeg {
  readonly leg: Leg;
  readonly from: Waypoint;
  readonly to: Waypoint;
}

/** Waypoints with both a usable arrival and departure, in order. */
function timedWaypoints(trip: Trip): Waypoint[] {
  return trip.waypoints.filter(
    (waypoint) => arriveAbs(waypoint) !== null && departAbs(waypoint) !== null,
  );
}

/**
 * All timed legs for a trip. A `stop` end gets an ease phase, a `pass` end does
 * not (ADR 004).
 */
export function buildLegs(trip: Trip, policy: Policy): TimedLeg[] {
  const timed = timedWaypoints(trip);
  const legs: TimedLeg[] = [];
  for (let index = 0; index < timed.length - 1; index += 1) {
    const from = timed[index]!;
    const to = timed[index + 1]!;
    const leg = buildLeg({
      tI: departAbs(from)!,
      tJ: arriveAbs(to)!,
      sI: from.sM,
      sJ: to.sM,
      easeStart: from.stopType === "stop",
      easeEnd: to.stopType === "stop",
      accelTimeS: policy.accel_time_s,
    });
    if (leg !== null) legs.push({ leg, from, to });
  }
  return legs;
}

function segmentIndexAt(trip: Trip, sM: number): number {
  let offset = 0;
  for (let index = 0; index < trip.segments.length; index += 1) {
    const segment = trip.segments[index]!;
    if (sM <= offset + segment.lengthM || index === trip.segments.length - 1) return index;
    offset += segment.lengthM;
  }
  return trip.segments.length - 1;
}

/** (lat, lon) at distance `sM` along the trip's oriented polyline. */
export function pointOnTrip(trip: Trip, sM: number): { lat: number; lon: number } {
  if (trip.segments.length === 0) throw new Error(`trip ${trip.tripId} has no geometry`);

  const index = segmentIndexAt(trip, sM);
  const segment = trip.segments[index]!;

  let offset = 0;
  for (let previous = 0; previous < index; previous += 1) {
    offset += trip.segments[previous]!.lengthM;
  }

  const distance = Math.max(0, Math.min(segment.lengthM, sM - offset));
  return pointAt(segment, distance);
}

function bearingAt(trip: Trip, sM: number): number {
  const segment: SegmentGeom = trip.segments[segmentIndexAt(trip, sM)]!;
  const point = pointAt(segment, 0);
  // A short step forward gives a stable tangent without extra state.
  const ahead = pointAt(segment, Math.min(segment.lengthM, 25));
  if (ahead.lat === point.lat && ahead.lon === point.lon && segment.coordinates.length > 1) {
    return bearing(segment.coordinates[0]!, segment.coordinates[1]!);
  }
  return bearing(point, ahead);
}

/** The next STOP row at or beyond the current distance, and its printed time. */
export function nextStop(
  trip: Trip,
  sM: number,
): { code: string | null; time: string | null } {
  for (const waypoint of trip.waypoints) {
    if (waypoint.sM >= sM - 1e-6 && waypoint.stopType === "stop") {
      const printed = waypoint.arriveSod ?? waypoint.departSod;
      return {
        code: waypoint.stationCode,
        time: printed === null ? null : formatSod(printed),
      };
    }
  }
  return { code: null, time: null };
}

function make(
  trip: Trip,
  sM: number,
  status: TrainStatus,
  speedMps: number,
  from: Waypoint,
  to: Waypoint,
): TrainPosition {
  const point = pointOnTrip(trip, sM);
  const stop = nextStop(trip, sM);
  return {
    tripId: trip.tripId,
    trainNo: trip.trainNo,
    name: trip.name,
    relation: trip.relation,
    lat: point.lat,
    lon: point.lon,
    bearing: bearingAt(trip, sM),
    status,
    sM,
    fromCode: from.stationCode,
    toCode: to.stationCode,
    nextStopCode: stop.code,
    nextStopTime: stop.time,
    speedKmh: speedMps * 3.6,
    estimated: true,
    coarse: trip.hasUntimedMarkers,
    hasBypassedWaypoints: trip.hasBypassedWaypoints,
    hasStraightLineSegment: trip.hasStraightLineSegment,
    serviceClass: trip.serviceClass,
    motionModel: MOTION_MODEL,
  };
}

function positionFor(
  trip: Trip,
  legs: readonly TimedLeg[],
  elapsed: number,
  policy: Policy,
): TrainPosition | null {
  // Dwell at a station, or running along a leg.
  for (const { leg, from, to } of legs) {
    const arriveA = arriveAbs(from);
    const departA = departAbs(from);
    if (arriveA !== null && departA !== null && arriveA <= elapsed && elapsed < departA) {
      return make(trip, from.sM, STATUS_AT_STATION, 0, from, to);
    }
    if (leg.tI <= elapsed && elapsed <= leg.tJ) {
      if (elapsed <= leg.tI) return make(trip, leg.sI, STATUS_AT_STATION, 0, from, to);
      if (elapsed >= leg.tJ) return make(trip, leg.sJ, STATUS_AT_STATION, 0, from, to);
      return make(trip, distanceAt(leg, elapsed), STATUS_RUNNING, speedAt(leg, elapsed), from, to);
    }
  }

  const last = legs[legs.length - 1];
  if (last && last.leg.tJ <= elapsed && elapsed <= last.leg.tJ + policy.terminal_linger_s) {
    return make(trip, last.leg.sJ, STATUS_AT_STATION, 0, last.from, last.to);
  }
  return null;
}

/**
 * Estimated positions of every visible, active trip at `instant`.
 *
 * `instant` is epoch milliseconds. The output order is date-major then trip
 * order, matching the Python reference.
 */
export function positionsAt(
  snapshot: ScheduleSnapshot,
  instant: number,
  policy: Policy = snapshot.policy,
): TrainPosition[] {
  const local = wibFromEpochMs(instant);
  const positions: TrainPosition[] = [];
  const legCache = new Map<string, TimedLeg[]>();

  for (let k = 0; k <= snapshot.maxDayOffset; k += 1) {
    // elapsed = (instant - midnight(date(t) - k)).  Because the instant's own
    // seconds-of-day are `local.secondsOfDay`, that is exactly k days + sod.
    const elapsed = k * SECONDS_PER_DAY + local.secondsOfDay;

    for (const trip of snapshot.trips) {
      if (!isVisible(trip, policy)) continue;
      if (!isShownByClass(trip, policy)) continue;
      if (!(trip.firstAbs <= elapsed && elapsed <= trip.lastAbs)) continue;

      let legs = legCache.get(trip.tripId);
      if (legs === undefined) {
        legs = buildLegs(trip, policy);
        legCache.set(trip.tripId, legs);
      }
      if (legs.length === 0) continue;

      const position = positionFor(trip, legs, elapsed, policy);
      if (position !== null) positions.push(position);
    }
  }

  return positions;
}
