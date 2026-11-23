/**
 * Query helpers the UI needs on top of `positionsAt`.
 *
 * These are NEW behaviour: `engine/position.py` has no station board and no
 * "minutes away" headline, so this module defines its own contract. Everything
 * here is pure — the snapshot, an instant and a policy go in, data comes out.
 *
 * Two deliberate differences from the parity-critical `nextStop()` in
 * `position.ts`:
 *
 * - the board lists only rows you can actually board (never the terminus, never
 *   a `pass` row), and
 * - `nextStopAhead` looks STRICTLY ahead in distance, so a train standing at its
 *   origin reports the following stop rather than the one it is sitting at.
 *   `position.nextStopCode` keeps the Python semantics and must not change.
 */
import { addDays, formatSod, formatSodHm, midnightEpochMs, wibFromEpochMs } from "./time";
import {
  arriveAbs,
  departAbs,
  isShownByClass,
  isVisible,
  SECONDS_PER_DAY,
  type Policy,
  type ScheduleSnapshot,
  type ServiceClass,
  type Trip,
} from "./types";

export const BOARD_WINDOW_S = 3 * 3600;
export const BOARD_LIMIT = 10;

export interface BoardEntry {
  readonly tripId: string;
  readonly trainNo: string;
  readonly name: string;
  readonly relation: string;
  readonly serviceClass: ServiceClass;
  readonly stationCode: string;
  /** printed station-local time, `HH:MM` */
  readonly scheduledTime: string;
  /** whole days between the query's WIB date and the departure's WIB date */
  readonly dayOffset: number;
  /** epoch milliseconds of the scheduled departure */
  readonly departsAtMs: number;
  readonly coarse: boolean;
  readonly hiddenByDefault: boolean;
}

export interface BoardOptions {
  readonly windowS?: number;
  readonly limit?: number;
}

interface Candidate extends BoardEntry {
  readonly departsAtMs: number;
}

/**
 * The next departures from `stationCode` within `windowS` (default 3 hours).
 *
 * Scans the previous service dates for after-midnight tails (k >= 0) and the
 * NEXT service date (k = -1) for trips that begin just after midnight, which is
 * how the Gapeka prints a train that starts at 01:00.
 */
export function stationBoard(
  snapshot: ScheduleSnapshot,
  stationCode: string,
  instant: number,
  policy: Policy = snapshot.policy,
  options: BoardOptions = {},
): BoardEntry[] {
  const windowMs = (options.windowS ?? BOARD_WINDOW_S) * 1000;
  const limit = options.limit ?? BOARD_LIMIT;
  const latest = instant + windowMs;

  const local = wibFromEpochMs(instant);
  const candidates: Candidate[] = [];

  for (let k = -1; k <= snapshot.maxDayOffset; k += 1) {
    const serviceDate = addDays(local.date, -k);
    const serviceMidnightMs = midnightEpochMs(serviceDate);

    for (const trip of snapshot.trips) {
      if (!isVisible(trip, policy)) continue;
      if (!isShownByClass(trip, policy)) continue;

      const index = trip.rows.findIndex(
        (row) => row.stationCode === stationCode && row.stopType === "stop",
      );
      if (index < 0) continue;
      // A terminus is not a boardable departure, even though the export mirrors
      // the arrival into the departure column for the last row.
      if (index === trip.rows.length - 1) continue;

      const row = trip.rows[index]!;
      const departAbsValue = departAbs(row);
      if (departAbsValue === null) continue;

      const departsAtMs = serviceMidnightMs + departAbsValue * 1000;
      if (departsAtMs < instant || departsAtMs > latest) continue;

      const departureDate = wibFromEpochMs(departsAtMs).date;
      const dayOffset = Math.round(
        (midnightEpochMs(departureDate) - midnightEpochMs(local.date)) / (SECONDS_PER_DAY * 1000),
      );

      candidates.push({
        tripId: trip.tripId,
        trainNo: trip.trainNo,
        name: trip.name,
        relation: trip.relation,
        serviceClass: trip.serviceClass,
        stationCode,
        scheduledTime: formatSodHm(row.departSod!),
        dayOffset,
        departsAtMs,
        coarse: trip.hasUntimedMarkers,
        hiddenByDefault: trip.hiddenByDefault,
      });
    }
  }

  candidates.sort((a, b) => a.departsAtMs - b.departsAtMs);
  return candidates.slice(0, limit);
}

export interface UpcomingStop {
  readonly code: string;
  /** printed station-local time, `HH:MM` */
  readonly scheduledTime: string;
  /** printed station-local time, `HH:MM:SS` */
  readonly scheduledTimeS: string;
  /** seconds of day of the arrival (station-local) */
  readonly sod: number;
  /** whole days after the service date the stop falls on */
  readonly dayOffset: number;
  /** floor of the remaining minutes; never rounded up */
  readonly minutesAway: number;
}

/**
 * The next scheduled `stop` strictly ahead of `sM`, with its printed time and
 * the minutes remaining from `elapsed` (seconds since the service-date midnight).
 *
 * `pass` and `unknown_untimed` rows are skipped: the headline names a station the
 * train actually calls at.
 */
export function nextStopAhead(trip: Trip, sM: number, elapsed: number): UpcomingStop | null {
  for (const waypoint of trip.waypoints) {
    if (waypoint.sM <= sM) continue;
    if (waypoint.stopType !== "stop") continue;
    const arrive = arriveAbs(waypoint);
    if (arrive === null) continue;
    if (arrive <= elapsed) continue;
    return {
      code: waypoint.stationCode,
      scheduledTime: formatSodHm(waypoint.arriveSod ?? waypoint.departSod ?? 0),
      scheduledTimeS: formatSod(waypoint.arriveSod ?? waypoint.departSod ?? 0),
      sod: waypoint.arriveSod ?? waypoint.departSod ?? 0,
      dayOffset: waypoint.arriveDayOffset,
      minutesAway: Math.floor((arrive - elapsed) / 60),
    };
  }
  return null;
}
