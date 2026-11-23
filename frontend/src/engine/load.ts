/**
 * Loading the exported schedule into the engine model.
 *
 * `buildSnapshot` is PURE: it takes already-parsed JSON and returns immutable
 * structures. Fetching lives in the worker, so this module stays testable and
 * the engine stays free of I/O.
 *
 * Two export details are easy to get wrong and are covered by tests:
 *
 * - `waypoints.code` is an INDEX into the sorted station list, not a station
 *   code (`pipeline/export_web.py` writes `by_code`), and
 * - `-1` means "no time" in the `arrive` / `depart` columns.
 */
import { cumulativeDistances } from "./geometry";
import { decodePolyline } from "./polyline";
import {
  type Attribution,
  type Policy,
  SECONDS_PER_DAY,
  type ScheduleSnapshot,
  type SegmentGeom,
  type ServiceClass,
  type Station,
  type StopType,
  type Trip,
  type TripGeometryStatus,
  type Waypoint,
} from "./types";

// --- raw export shapes (mirror pipeline/export_web.py) ----------------------

export interface RawManifest {
  readonly schema: number;
  readonly version_name: string;
  readonly effective_from: string;
  readonly effective_to: string | null;
  readonly policy: Policy;
  readonly content_hash: string;
  readonly max_day_offset: number;
  readonly counts: {
    readonly stations: number;
    readonly segments: number;
    readonly trips: number;
  };
  readonly attribution: Attribution;
  readonly files?: Readonly<Record<string, string>>;
}

export interface RawStation {
  readonly code: string;
  readonly official_name: string;
  readonly disambiguator: string | null;
  readonly lat: number | null;
  readonly lon: number | null;
}

export interface RawStations {
  readonly schema: number;
  readonly stations: readonly RawStation[];
}

export interface RawSegment {
  readonly from: string;
  readonly to: string;
  readonly length_m: number;
  readonly quality: string;
  readonly polyline: string;
  readonly points: number;
}

export interface RawSegments {
  readonly schema: number;
  readonly precision: number;
  readonly segments: readonly RawSegment[];
}

export interface RawWaypointColumns {
  readonly code: readonly number[];
  readonly s_m: readonly number[];
  readonly arrive: readonly number[];
  readonly depart: readonly number[];
  readonly stop_type: readonly number[];
  readonly bypassed: readonly number[];
}

export interface RawTrip {
  readonly trip_id: string;
  readonly train_no: string;
  readonly name: string;
  readonly relation: string;
  readonly service_class: string;
  readonly status: string;
  readonly flags: number;
  readonly hidden_by_default: boolean;
  readonly first_s: number;
  readonly last_s: number;
  readonly length_m: number;
  readonly segment_ids: readonly number[];
  readonly reversed: readonly number[];
  readonly waypoints: RawWaypointColumns;
}

export interface RawTrips {
  readonly schema: number;
  readonly stop_types: readonly string[];
  readonly trips: readonly RawTrip[];
}

export interface RawExport {
  readonly manifest: RawManifest;
  readonly stations: RawStations;
  readonly segments: RawSegments;
  readonly trips: RawTrips;
}

// --- trip flags (mirror pipeline/export_web.py) -----------------------------

export const FLAG_COARSE = 1;
export const FLAG_BYPASSED = 2;
export const FLAG_STRAIGHT_LINE = 4;

const SERVICE_CLASSES = ["reguler", "fakultatif", "unknown"] as const;
const GEOMETRY_STATUSES = [
  "complete",
  "complete_estimated",
  "has_fallback",
  "has_unmeasured",
] as const;

function serviceClassOf(value: string): ServiceClass {
  return (SERVICE_CLASSES as readonly string[]).includes(value)
    ? (value as ServiceClass)
    : "unknown";
}

function geometryStatusOf(value: string): TripGeometryStatus {
  return (GEOMETRY_STATUSES as readonly string[]).includes(value)
    ? (value as TripGeometryStatus)
    : "has_unmeasured";
}

/** The export encodes "no time" as -1, not null. */
function absOrNull(value: number): number | null {
  return value < 0 ? null : value;
}

/** Absolute seconds -> seconds of day; the inverse of the export's addition. */
function sodOf(abs: number | null): number | null {
  if (abs === null) return null;
  return abs % SECONDS_PER_DAY;
}

function dayOffsetOf(abs: number | null): number {
  if (abs === null) return 0;
  return Math.floor(abs / SECONDS_PER_DAY);
}

/** Decode every segment once, in its canonical direction. */
export function decodeSegments(raw: RawSegments): SegmentGeom[] {
  return raw.segments.map((segment) => {
    const coordinates = decodePolyline(segment.polyline, raw.precision);
    return {
      fromCode: segment.from,
      toCode: segment.to,
      lengthM: segment.length_m,
      quality: segment.quality,
      coordinates,
      cumulativeM: cumulativeDistances(coordinates),
    };
  });
}

/**
 * Orient a segment for one trip (F1). The export stores each polyline once, in
 * its canonical direction; a trip that runs it backwards sets `reversed = 1`.
 */
export function orientSegment(segment: SegmentGeom, reversed: boolean): SegmentGeom {
  if (!reversed) return segment;
  const coordinates = [...segment.coordinates].reverse();
  return {
    fromCode: segment.toCode,
    toCode: segment.fromCode,
    lengthM: segment.lengthM,
    quality: segment.quality,
    coordinates,
    cumulativeM: cumulativeDistances(coordinates),
  };
}

function buildRows(
  raw: RawTrip,
  stationCodes: readonly string[],
  stopTypes: readonly string[],
): Waypoint[] {
  const columns = raw.waypoints;
  const rows: Waypoint[] = [];

  for (let index = 0; index < columns.code.length; index += 1) {
    const stationIndex = columns.code[index]!;
    const code = stationIndex >= 0 ? stationCodes[stationIndex] : undefined;
    if (code === undefined) {
      throw new Error(
        `trip ${raw.trip_id}: waypoint ${index} refers to unknown station index ${stationIndex}`,
      );
    }

    const arrive = absOrNull(columns.arrive[index]!);
    const depart = absOrNull(columns.depart[index]!);

    rows.push({
      seq: index,
      stationCode: code,
      stopType: (stopTypes[columns.stop_type[index]!] ?? "stop") as StopType,
      arriveSod: sodOf(arrive),
      departSod: sodOf(depart),
      arriveDayOffset: dayOffsetOf(arrive),
      departDayOffset: dayOffsetOf(depart),
      sM: columns.s_m[index]!,
      bypassed: columns.bypassed[index] === 1,
    });
  }

  return rows;
}

function buildTrip(
  raw: RawTrip,
  stationCodes: readonly string[],
  stopTypes: readonly string[],
  canonical: readonly SegmentGeom[],
): Trip {
  const rows = buildRows(raw, stationCodes, stopTypes);

  const segments = raw.segment_ids.map((segmentId, position) => {
    const segment = canonical[segmentId];
    if (!segment) {
      throw new Error(`trip ${raw.trip_id}: segment id ${segmentId} is out of range`);
    }
    return orientSegment(segment, raw.reversed[position] === 1);
  });

  return {
    tripId: raw.trip_id,
    trainNo: raw.train_no,
    name: raw.name,
    relation: raw.relation,
    // The export has no `book` column; the trip id encodes it (`b1-`, `b2-`).
    book: raw.trip_id.startsWith("b2-") ? 2 : 1,
    serviceClass: serviceClassOf(raw.service_class),
    geometryStatus: geometryStatusOf(raw.status),
    hasUntimedMarkers: (raw.flags & FLAG_COARSE) !== 0,
    hasBypassedWaypoints: (raw.flags & FLAG_BYPASSED) !== 0,
    // Mirrors `snapshot.py`: derived from the qualities actually used.
    hasStraightLineSegment: segments.some((segment) => segment.quality === "straight_line"),
    // Bypassed rows are display-only; `snapshot.py` drops them from the engine.
    waypoints: rows.filter((row) => !row.bypassed),
    rows,
    segments,
    firstAbs: raw.first_s,
    lastAbs: raw.last_s,
    totalLengthM: raw.length_m,
    hiddenByDefault: raw.hidden_by_default,
  };
}

/** Build the immutable snapshot the pure engine functions consume. */
export function buildSnapshot(raw: RawExport): ScheduleSnapshot {
  const stationCodes = raw.stations.stations.map((entry) => entry.code);

  const stations = new Map<string, Station>();
  for (const entry of raw.stations.stations) {
    stations.set(entry.code, {
      code: entry.code,
      officialName: entry.official_name,
      disambiguator: entry.disambiguator,
      lat: entry.lat,
      lon: entry.lon,
    });
  }

  const canonical = decodeSegments(raw.segments);

  return {
    versionName: raw.manifest.version_name,
    effectiveFrom: raw.manifest.effective_from,
    effectiveTo: raw.manifest.effective_to,
    contentHash: raw.manifest.content_hash,
    maxDayOffset: raw.manifest.max_day_offset,
    policy: raw.manifest.policy,
    trips: raw.trips.trips.map((trip) =>
      buildTrip(trip, stationCodes, raw.trips.stop_types, canonical),
    ),
    stations,
    attribution: raw.manifest.attribution,
  };
}
