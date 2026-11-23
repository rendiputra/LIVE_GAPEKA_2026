/**
 * The engine's data model — the TypeScript mirror of `engine/model.py`.
 *
 * Everything here is plain data: no classes with behaviour, no I/O, no clock.
 * The pure functions in `profile`, `geometry`, `position` and `queries` read
 * these and nothing else.
 */

export const MOTION_MODEL = "trapezoid_v1" as const;

/** Every Java station is WIB; the engine never reads a system time zone. */
export const WIB_OFFSET_S = 7 * 3600;
export const SECONDS_PER_DAY = 86_400;

export const STATUS_AT_STATION = "at_station" as const;
export const STATUS_RUNNING = "running" as const;
export type TrainStatus = typeof STATUS_AT_STATION | typeof STATUS_RUNNING;

export type GeometryPolicy = "complete_and_estimated" | "complete_only" | "allow_fallback";
export type ServiceClass = "reguler" | "fakultatif" | "unknown";
export type StopType = "stop" | "pass" | "unknown_untimed";
export type TripGeometryStatus =
  | "complete"
  | "complete_estimated"
  | "has_fallback"
  | "has_unmeasured";

/**
 * Explicit, immutable query policy. Nothing is hidden or defaulted silently
 * (ADR 002: `calendar_policy` must be passed, never assumed).
 */
export interface Policy {
  readonly calendar_policy: string;
  readonly show_fakultatif: boolean;
  readonly enforce_effective_from: boolean;
  readonly geometry_policy: GeometryPolicy;
  readonly accel_time_s: number;
  readonly origin_lead_s: number;
  readonly terminal_linger_s: number;
  readonly max_day_offset: number;
}

/** Defaults mirror `engine/model.py:Policy`. */
export const DEFAULT_POLICY: Policy = {
  calendar_policy: "regular_daily_assumed",
  show_fakultatif: false,
  enforce_effective_from: false,
  geometry_policy: "complete_and_estimated",
  accel_time_s: 60,
  origin_lead_s: 0,
  terminal_linger_s: 0,
  max_day_offset: 2,
};

/** One printed row of a trip, with its distance along the trip polyline. */
export interface Waypoint {
  readonly seq: number;
  readonly stationCode: string;
  readonly stopType: StopType;
  /** seconds from the start of the SERVICE DATE, or null when untimed */
  readonly arriveSod: number | null;
  readonly departSod: number | null;
  readonly arriveDayOffset: number;
  readonly departDayOffset: number;
  /** cumulative distance along the trip polyline */
  readonly sM: number;
  readonly bypassed: boolean;
}

export interface Coordinate {
  readonly lat: number;
  readonly lon: number;
}

/** A routed segment with cumulative distances for fast point lookup. */
export interface SegmentGeom {
  readonly fromCode: string;
  readonly toCode: string;
  readonly lengthM: number;
  readonly quality: string;
  /** oriented from -> to */
  readonly coordinates: readonly Coordinate[];
  readonly cumulativeM: readonly number[];
}

/** A trip ready for position estimation. */
export interface Trip {
  readonly tripId: string;
  readonly trainNo: string;
  readonly name: string;
  readonly relation: string;
  /** 1 = intercity/regional, 2 = local/agglomeration. From the trip id. */
  readonly book: number;
  readonly serviceClass: ServiceClass;
  readonly geometryStatus: TripGeometryStatus;
  readonly hasUntimedMarkers: boolean;
  readonly hasBypassedWaypoints: boolean;
  readonly hasStraightLineSegment: boolean;
  /** Engine waypoints: bypassed rows are excluded, exactly as `snapshot.py` does. */
  readonly waypoints: readonly Waypoint[];
  /** Every printed row, including bypassed ones, for display only. */
  readonly rows: readonly Waypoint[];
  readonly segments: readonly SegmentGeom[];
  readonly firstAbs: number;
  readonly lastAbs: number;
  readonly totalLengthM: number;
  readonly hiddenByDefault: boolean;
}

export interface Station {
  readonly code: string;
  readonly officialName: string;
  readonly disambiguator: string | null;
  readonly lat: number | null;
  readonly lon: number | null;
}

export interface ScheduleSnapshot {
  readonly versionName: string;
  readonly effectiveFrom: string;
  readonly effectiveTo: string | null;
  readonly contentHash: string;
  readonly maxDayOffset: number;
  readonly policy: Policy;
  readonly trips: readonly Trip[];
  readonly stations: ReadonlyMap<string, Station>;
  readonly attribution: Attribution;
}

export interface Attribution {
  readonly osm: string;
  readonly osm_url: string;
  readonly disclaimer: string;
}

/** One train's estimated position at an instant. */
export interface TrainPosition {
  readonly tripId: string;
  readonly trainNo: string;
  readonly name: string;
  readonly relation: string;
  readonly book: number;
  readonly lat: number;
  readonly lon: number;
  readonly bearing: number;
  readonly status: TrainStatus;
  readonly sM: number;
  readonly fromCode: string;
  readonly toCode: string;
  readonly nextStopCode: string | null;
  readonly nextStopTime: string | null;
  readonly speedKmh: number;
  readonly estimated: true;
  readonly coarse: boolean;
  readonly hasBypassedWaypoints: boolean;
  readonly hasStraightLineSegment: boolean;
  readonly serviceClass: ServiceClass;
  readonly motionModel: typeof MOTION_MODEL;
}

/** Absolute seconds since service-date midnight, honouring the day offset. */
export function arriveAbs(waypoint: Waypoint): number | null {
  if (waypoint.arriveSod === null) return null;
  return waypoint.arriveSod + SECONDS_PER_DAY * waypoint.arriveDayOffset;
}

export function departAbs(waypoint: Waypoint): number | null {
  if (waypoint.departSod === null) return null;
  return waypoint.departSod + SECONDS_PER_DAY * waypoint.departDayOffset;
}

/** E7: which geometry statuses may be shown. `has_unmeasured` never is. */
export function isVisible(trip: Trip, policy: Policy): boolean {
  if (trip.geometryStatus === "has_unmeasured") return false;
  if (policy.geometry_policy === "allow_fallback") return true;
  if (policy.geometry_policy === "complete_only") return trip.geometryStatus === "complete";
  return trip.geometryStatus === "complete" || trip.geometryStatus === "complete_estimated";
}

/**
 * A fakultatif trip — and any trip whose class is unknown — is hidden unless
 * explicitly shown (E3). Mirrors `engine/position.py:_visible`.
 */
export function isShownByClass(trip: Trip, policy: Policy): boolean {
  return policy.show_fakultatif || trip.serviceClass === "reguler";
}
