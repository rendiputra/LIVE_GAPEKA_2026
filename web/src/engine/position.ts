// positions_at ported from engine/position.py.
// PURE: input = prepared dataset + instant + policy; no DOM, no network.
//
// Time model (E2): every Java station is WIB = UTC+7, with no DST, so the local
// clock is fixed arithmetic on epoch seconds. Schedule times are seconds from the
// start of the SERVICE DATE. For a query instant we scan service dates
// (today - k) for k in 0..maxDayOffset, so a trip that started yesterday still
// appears after midnight.

import {
  FLAG_BYPASSED,
  FLAG_COARSE,
  FLAG_STRAIGHT_LINE,
  type Policy,
  type SegmentData,
  type StationData,
  type TripData,
} from "./types";
import { bearing, buildSegment, pointAt, type LatLon, type SegmentGeometry } from "./polyline";
import { buildLeg, distanceAt, speedAt, type Leg } from "./profile";

export const WIB_OFFSET_S = 7 * 3600;
export const SECONDS_PER_DAY = 86400;

export interface PreparedWaypoint {
  codeIndex: number;
  stationCode: string;
  sM: number;
  arriveAbs: number | null;
  departAbs: number | null;
  stopType: string;
  timed: boolean;
  /** Bypassed rows are listed in the UI but never form a leg, exactly as in Python. */
  bypassed: boolean;
}

export interface PreparedTrip {
  data: TripData;
  waypoints: PreparedWaypoint[];
  segments: SegmentGeometry[];
  segmentOffsets: number[];
  firstS: number;
  lastS: number;
  coarse: boolean;
  bypassed: boolean;
  hasStraightLine: boolean;
}

export interface Dataset {
  manifest: {
    max_day_offset: number;
    version_name: string;
    effective_from: string;
  };
  stations: StationData[];
  stationByCode: Map<string, StationData>;
  segments: SegmentData[];
  trips: PreparedTrip[];
}

export interface TrainPosition {
  tripId: string;
  trainNo: string;
  name: string;
  relation: string;
  lat: number;
  lon: number;
  bearing: number;
  status: "at_station" | "running";
  sM: number;
  fromCode: string;
  toCode: string;
  nextStopCode: string | null;
  nextStopTime: string | null;
  speedKmh: number;
  estimated: true;
  coarse: boolean;
  hasBypassedWaypoints: boolean;
  hasStraightLineSegment: boolean;
  serviceClass: string;
}

function sod(value: number | null): number | null {
  return value === null ? null : value % SECONDS_PER_DAY;
}

function formatSod(value: number | null): string | null {
  if (value === null) return null;
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = Math.floor(value % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function prepare(
  manifest: Dataset["manifest"],
  stations: StationData[],
  segments: SegmentData[],
  trips: TripData[],
  stopTypes: string[],
): Dataset {
  const stationByCode = new Map(stations.map((station) => [station.code, station]));

  const preparedTrips: PreparedTrip[] = trips.map((trip) => {
    const waypoints: PreparedWaypoint[] = trip.waypoints.code.map((codeIndex, i) => {
      const station = stations[codeIndex];
      const arrive = trip.waypoints.arrive[i];
      const depart = trip.waypoints.depart[i];
      return {
        codeIndex,
        stationCode: station ? station.code : "?",
        sM: trip.waypoints.s_m[i],
        arriveAbs: arrive < 0 ? null : arrive,
        departAbs: depart < 0 ? null : depart,
        stopType: stopTypes[trip.waypoints.stop_type[i]] ?? "stop",
        timed: arrive >= 0 || depart >= 0,
        bypassed: (trip.waypoints.bypassed?.[i] ?? 0) === 1,
      };
    });

    const geometry = trip.segment_ids.map((id, i) =>
      buildSegment(segments[id], trip.reversed[i] === 1),
    );
    const offsets: number[] = [];
    let running = 0;
    for (const segment of geometry) {
      offsets.push(running);
      running += segment.lengthM;
    }

    return {
      data: trip,
      waypoints,
      segments: geometry,
      segmentOffsets: offsets,
      firstS: trip.first_s,
      lastS: trip.last_s,
      coarse: (trip.flags & FLAG_COARSE) !== 0,
      bypassed: (trip.flags & FLAG_BYPASSED) !== 0,
      hasStraightLine: (trip.flags & FLAG_STRAIGHT_LINE) !== 0,
    };
  });

  return {
    manifest,
    stations,
    stationByCode,
    segments,
    trips: preparedTrips,
  };
}

export function pointOnTrip(trip: PreparedTrip, sM: number): LatLon {
  if (trip.segments.length === 0) throw new Error(`trip ${trip.data.trip_id} has no geometry`);
  for (let i = 0; i < trip.segments.length; i += 1) {
    const segment = trip.segments[i];
    const offset = trip.segmentOffsets[i];
    if (sM <= offset + segment.lengthM || i === trip.segments.length - 1) {
      return pointAt(segment, Math.max(0, Math.min(segment.lengthM, sM - offset)));
    }
  }
  const last = trip.segments[trip.segments.length - 1];
  return last.points[last.points.length - 1];
}

function segmentAt(trip: PreparedTrip, sM: number): { segment: SegmentGeometry; offset: number } {
  for (let i = 0; i < trip.segments.length; i += 1) {
    const segment = trip.segments[i];
    const offset = trip.segmentOffsets[i];
    if (sM <= offset + segment.lengthM || i === trip.segments.length - 1) {
      return { segment, offset };
    }
  }
  const i = trip.segments.length - 1;
  return { segment: trip.segments[i], offset: trip.segmentOffsets[i] };
}

function bearingAt(trip: PreparedTrip, sM: number): number {
  const { segment, offset } = segmentAt(trip, sM);
  const local = Math.max(0, Math.min(segment.lengthM, sM - offset));
  const point = pointAt(segment, local);
  const ahead = pointAt(segment, Math.min(segment.lengthM, local + 25));
  if (ahead[0] === point[0] && ahead[1] === point[1] && segment.points.length > 1) {
    return bearing(segment.points[0], segment.points[1]);
  }
  return bearing(point, ahead);
}

export function legsOf(trip: PreparedTrip, policy: Policy): Array<{ leg: Leg; a: PreparedWaypoint; b: PreparedWaypoint }> {
  // Bypassed rows are display-only: they have no reliable distance, so they must
  // not create a leg. This mirrors the Python snapshot, which never loads them.
  const timed = trip.waypoints.filter(
    (w) => !w.bypassed && w.arriveAbs !== null && w.departAbs !== null,
  );
  const legs: Array<{ leg: Leg; a: PreparedWaypoint; b: PreparedWaypoint }> = [];
  for (let i = 0; i + 1 < timed.length; i += 1) {
    const a = timed[i];
    const b = timed[i + 1];
    const leg = buildLeg(
      a.departAbs as number,
      b.arriveAbs as number,
      a.sM,
      b.sM,
      a.stopType === "stop",
      b.stopType === "stop",
      policy.accelTimeS,
    );
    if (leg) legs.push({ leg, a, b });
  }
  return legs;
}

function nextStop(trip: PreparedTrip, sM: number): { code: string | null; time: string | null } {
  for (const waypoint of trip.waypoints) {
    if (waypoint.bypassed) continue;
    if (waypoint.sM >= sM - 1e-6 && waypoint.stopType === "stop") {
      const printed = sod(waypoint.arriveAbs) ?? sod(waypoint.departAbs);
      return { code: waypoint.stationCode, time: formatSod(printed) };
    }
  }
  return { code: null, time: null };
}

function isVisible(trip: PreparedTrip, policy: Policy): boolean {
  if (policy.showFakultatif) return true;
  return trip.data.service_class === "reguler";
}

function make(
  trip: PreparedTrip,
  sM: number,
  status: "at_station" | "running",
  speedMps: number,
  a: PreparedWaypoint,
  b: PreparedWaypoint,
): TrainPosition {
  const [lat, lon] = pointOnTrip(trip, sM);
  const next = nextStop(trip, sM);
  return {
    tripId: trip.data.trip_id,
    trainNo: trip.data.train_no,
    name: trip.data.name,
    relation: trip.data.relation,
    lat,
    lon,
    bearing: bearingAt(trip, sM),
    status,
    sM,
    fromCode: a.stationCode,
    toCode: b.stationCode,
    nextStopCode: next.code,
    nextStopTime: next.time,
    speedKmh: speedMps * 3.6,
    estimated: true,
    coarse: trip.coarse,
    hasBypassedWaypoints: trip.bypassed,
    hasStraightLineSegment: trip.hasStraightLine,
    serviceClass: trip.data.service_class,
  };
}

function positionFor(
  trip: PreparedTrip,
  legs: Array<{ leg: Leg; a: PreparedWaypoint; b: PreparedWaypoint }>,
  elapsed: number,
  policy: Policy,
): TrainPosition | null {
  for (const { leg, a, b } of legs) {
    if (a.arriveAbs !== null && a.departAbs !== null && a.arriveAbs <= elapsed && elapsed < a.departAbs) {
      return make(trip, a.sM, "at_station", 0, a, b);
    }
    if (leg.tI <= elapsed && elapsed <= leg.tJ) {
      if (elapsed <= leg.tI) return make(trip, leg.sI, "at_station", 0, a, b);
      if (elapsed >= leg.tJ) return make(trip, leg.sJ, "at_station", 0, a, b);
      const s = distanceAt(leg, elapsed);
      const v = speedAt(leg, elapsed);
      return make(trip, s, "running", v, a, b);
    }
  }
  const last = legs[legs.length - 1];
  if (last && last.leg.tJ <= elapsed && elapsed <= last.leg.tJ + policy.terminalLingerS) {
    return make(trip, last.leg.sJ, "at_station", 0, last.a, last.b);
  }
  return null;
}

/** Local (WIB) epoch seconds from a UTC epoch-millisecond instant. */
export function localSeconds(instantMs: number): number {
  return Math.floor(instantMs / 1000) + WIB_OFFSET_S;
}

export function positionsAt(dataset: Dataset, instantMs: number, policy: Policy): TrainPosition[] {
  const localSec = localSeconds(instantMs);
  const today = Math.floor(localSec / SECONDS_PER_DAY);
  const maxOffset = dataset.manifest.max_day_offset ?? 0;
  const out: TrainPosition[] = [];

  for (let k = 0; k <= maxOffset; k += 1) {
    const serviceDay = today - k;
    const elapsed = localSec - serviceDay * SECONDS_PER_DAY;
    for (const trip of dataset.trips) {
      if (!isVisible(trip, policy)) continue;
      if (!(trip.firstS <= elapsed && elapsed <= trip.lastS)) continue;
      const legs = legsOf(trip, policy);
      if (legs.length === 0) continue;
      const position = positionFor(trip, legs, elapsed, policy);
      if (position) out.push(position);
    }
  }
  return out;
}

/** Service-day number (WIB) for an instant, for UI labels. */
export function serviceDayOf(instantMs: number): number {
  return Math.floor(localSeconds(instantMs) / SECONDS_PER_DAY);
}
