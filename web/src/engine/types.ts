// Wire types for web/public/data/*.json (B1) and the engine port (B2).
// These mirror the Python export exactly; nothing here is inferred.

export type StopType = "stop" | "pass" | "unknown_untimed";
export type ServiceClass = "reguler" | "fakultatif" | "unknown";
export type GeometryStatus = "complete" | "complete_estimated";

export const FLAG_COARSE = 1;
export const FLAG_BYPASSED = 2;
export const FLAG_STRAIGHT_LINE = 4;

export interface StationData {
  code: string;
  official_name: string;
  disambiguator: string | null;
  lat: number | null;
  lon: number | null;
}

export interface SegmentData {
  from: string;
  to: string;
  length_m: number;
  quality: string;
  polyline: string;
  points: number;
}

export interface WaypointColumns {
  code: number[];
  s_m: number[];
  arrive: number[];
  depart: number[];
  stop_type: number[];
  /** 1 when the row was bypassed for geometry (no coordinate). Display only. */
  bypassed?: number[];
}

export interface TripData {
  trip_id: string;
  train_no: string;
  name: string;
  relation: string;
  service_class: ServiceClass;
  status: GeometryStatus;
  flags: number;
  hidden_by_default: boolean;
  first_s: number;
  last_s: number;
  length_m: number;
  segment_ids: number[];
  reversed: number[];
  waypoints: WaypointColumns;
}

export interface Manifest {
  schema: number;
  version_name: string;
  effective_from: string;
  effective_to: string | null;
  max_day_offset: number;
  content_hash: string;
  policy: {
    calendar_policy: string;
    show_fakultatif: boolean;
    enforce_effective_from: boolean;
    geometry_policy: string;
    accel_time_s: number;
    origin_lead_s: number;
    terminal_linger_s: number;
    max_day_offset: number;
  };
  counts: { stations: number; segments: number; trips: number };
  attribution: {
    osm: string;
    osm_url: string;
    disclaimer: string;
    preview_banner: string;
  };
}

export interface Policy {
  showFakultatif: boolean;
  enforceEffectiveFrom: boolean;
  accelTimeS: number;
  terminalLingerS: number;
}

export function defaultPolicy(manifest: Manifest): Policy {
  return {
    showFakultatif: manifest.policy.show_fakultatif,
    enforceEffectiveFrom: manifest.policy.enforce_effective_from,
    accelTimeS: manifest.policy.accel_time_s,
    terminalLingerS: manifest.policy.terminal_linger_s,
  };
}
