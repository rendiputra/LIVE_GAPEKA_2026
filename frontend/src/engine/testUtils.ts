/**
 * Test-only builders. Keeping these out of production modules means the engine
 * ships no fixture-shaped conveniences that could be mistaken for API.
 */
import { cumulativeDistances } from "./geometry";
import type { RawExport } from "./load";
import {
  type Coordinate,
  DEFAULT_POLICY,
  type Policy,
  type SegmentGeom,
  type Station,
  type StopType,
  type Trip,
  type TripGeometryStatus,
  type Waypoint,
} from "./types";

export function segmentGeom(input: {
  fromCode: string;
  toCode: string;
  lengthM: number;
  coordinates: readonly Coordinate[];
  quality?: string;
}): SegmentGeom {
  return {
    fromCode: input.fromCode,
    toCode: input.toCode,
    lengthM: input.lengthM,
    quality: input.quality ?? "osm_routed",
    coordinates: input.coordinates,
    cumulativeM: cumulativeDistances(input.coordinates),
  };
}

export function waypoint(input: {
  seq?: number;
  stationCode: string;
  stopType?: StopType;
  arriveSod?: number | null;
  departSod?: number | null;
  arriveDayOffset?: number;
  departDayOffset?: number;
  sM: number;
  bypassed?: boolean;
}): Waypoint {
  return {
    seq: input.seq ?? 0,
    stationCode: input.stationCode,
    stopType: input.stopType ?? "stop",
    arriveSod: input.arriveSod ?? null,
    departSod: input.departSod ?? null,
    arriveDayOffset: input.arriveDayOffset ?? 0,
    departDayOffset: input.departDayOffset ?? 0,
    sM: input.sM,
    bypassed: input.bypassed ?? false,
  };
}

export function trip(input: {
  tripId?: string;
  trainNo?: string;
  name?: string;
  relation?: string;
  serviceClass?: Trip["serviceClass"];
  geometryStatus?: TripGeometryStatus;
  hasUntimedMarkers?: boolean;
  hasBypassedWaypoints?: boolean;
  hasStraightLineSegment?: boolean;
  waypoints: readonly Waypoint[];
  segments?: readonly SegmentGeom[];
  firstAbs: number;
  lastAbs: number;
  totalLengthM?: number;
}): Trip {
  const engineWaypoints = input.waypoints.filter((point) => !point.bypassed);
  return {
    tripId: input.tripId ?? "t1",
    trainNo: input.trainNo ?? "1",
    name: input.name ?? "",
    relation: input.relation ?? "",
    serviceClass: input.serviceClass ?? "reguler",
    geometryStatus: input.geometryStatus ?? "complete",
    hasUntimedMarkers: input.hasUntimedMarkers ?? false,
    hasBypassedWaypoints: input.hasBypassedWaypoints ?? false,
    hasStraightLineSegment: input.hasStraightLineSegment ?? false,
    waypoints: engineWaypoints,
    rows: input.waypoints,
    segments: input.segments ?? [],
    firstAbs: input.firstAbs,
    lastAbs: input.lastAbs,
    totalLengthM: input.totalLengthM ?? 0,
    hiddenByDefault: (input.serviceClass ?? "reguler") !== "reguler",
  };
}

export function station(input: {
  code: string;
  officialName?: string;
  disambiguator?: string | null;
  lat?: number | null;
  lon?: number | null;
}): Station {
  return {
    code: input.code,
    officialName: input.officialName ?? input.code,
    disambiguator: input.disambiguator ?? null,
    lat: input.lat ?? null,
    lon: input.lon ?? null,
  };
}

export function policy(overrides: Partial<Policy> = {}): Policy {
  return { ...DEFAULT_POLICY, ...overrides };
}

/**
 * Read the real exported bundle from `frontend/public/data/`.
 *
 * A test that needs real data must fail loudly when the export is missing,
 * with the command to fix it — silently skipping would let the parity gate
 * pass without ever comparing anything.
 */
export async function readExportedBundle(): Promise<RawExport> {
  const { readFile } = await import("node:fs/promises");
  const { join } = await import("node:path");
  const directory = join(process.cwd(), "public", "data");

  const readJson = async (name: string): Promise<unknown> => {
    try {
      return JSON.parse(await readFile(join(directory, name), "utf8"));
    } catch (error) {
      throw new Error(
        `cannot read ${directory}/${name}; run \`make export-frontend\` first (${String(error)})`,
      );
    }
  };

  return {
    manifest: (await readJson("manifest.json")) as RawExport["manifest"],
    stations: (await readJson("stations.json")) as RawExport["stations"],
    segments: (await readJson("segments.json")) as RawExport["segments"],
    trips: (await readJson("trips.json")) as RawExport["trips"],
  };
}

/** The Python-generated parity fixture, mapped to the frames the engine returns. */
export interface ParityFrame {
  readonly trip_id: string;
  readonly t_s: number;
  readonly present: boolean;
  readonly lat: number | null;
  readonly lon: number | null;
  readonly s_m: number | null;
  readonly speed_kmh: number | null;
  readonly status: string | null;
  readonly from: string | null;
  readonly to: string | null;
  readonly next_stop: string | null;
  readonly next_stop_time: string | null;
}

export interface ParityFixture {
  readonly seed: number;
  readonly service_date: string;
  readonly policy: Policy;
  readonly content_hash: string;
  readonly count: number;
  readonly trips_sampled: number;
  readonly frames: readonly ParityFrame[];
}

/** Read `engine/parity_frames.json` (repo root, gitignored, `make parity`). */
export async function readParityFixture(): Promise<ParityFixture> {
  const { readFile } = await import("node:fs/promises");
  const { join } = await import("node:path");
  const path = join(process.cwd(), "..", "engine", "parity_frames.json");
  try {
    return JSON.parse(await readFile(path, "utf8")) as ParityFixture;
  } catch (error) {
    throw new Error(`cannot read ${path}; run \`make parity\` first (${String(error)})`);
  }
}
