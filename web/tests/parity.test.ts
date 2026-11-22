// B3 parity: the TypeScript port must match the Python engine exactly.
//
// A mismatch is a bug to report, never a tolerance to widen. The tolerances here
// come from the specification: 1 m for lat/lon and s_m, 0.2 km/h for speed, and
// identical status/from/to/next stop.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { prepare, positionsAt, type Dataset } from "../src/engine/position";
import { defaultPolicy, type Manifest, type Policy } from "../src/engine/types";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const DATA = resolve(ROOT, "web/public/data");
const PARITY = resolve(ROOT, "engine/parity_frames.json");

const LAT_LON_TOL_M = 1.0;
const S_M_TOL_M = 1.0;
const SPEED_TOL_KMH = 0.2;

function loadDataset(): Dataset {
  const manifest: Manifest = JSON.parse(readFileSync(resolve(DATA, "manifest.json"), "utf8"));
  const stations = JSON.parse(readFileSync(resolve(DATA, "stations.json"), "utf8"));
  const segments = JSON.parse(readFileSync(resolve(DATA, "segments.json"), "utf8"));
  const trips = JSON.parse(readFileSync(resolve(DATA, "trips.json"), "utf8"));
  return prepare(
    manifest,
    stations.stations,
    segments.segments,
    trips.trips,
    trips.stop_types,
  );
}

function metresPerDegreeAt(lat: number): { lat: number; lon: number } {
  // Local scale is enough for a 1 m tolerance comparison.
  const mPerDegLat = 111_132.0;
  const mPerDegLon = 111_320.0 * Math.cos((lat * Math.PI) / 180);
  return { lat: mPerDegLat, lon: mPerDegLon };
}

function distanceM(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const scale = metresPerDegreeAt(aLat);
  const dy = (aLat - bLat) * scale.lat;
  const dx = (aLon - bLon) * scale.lon;
  return Math.sqrt(dx * dx + dy * dy);
}

describe("parity with the Python engine", () => {
  const dataset = loadDataset();
  const frames: Array<Record<string, unknown>> = JSON.parse(
    readFileSync(PARITY, "utf8"),
  ).frames;
  const manifest: Manifest = JSON.parse(readFileSync(resolve(DATA, "manifest.json"), "utf8"));
  const policy: Policy = defaultPolicy(manifest);
  // The fixture was generated with fakultatif visible, so parity uses that too.
  const parityPolicy: Policy = { ...policy, showFakultatif: true };

  const serviceMidnightMs = Date.UTC(2026, 11, 1, 0, 0, 0) - 7 * 3600 * 1000;

  it("has at least 5,000 samples covering every trip", () => {
    expect(frames.length).toBeGreaterThanOrEqual(5000);
    const trips = new Set(frames.map((frame) => frame.trip_id));
    expect(trips.size).toBe(dataset.trips.length);
  });

  it("matches every sampled instant", () => {
    let checked = 0;
    const failures: string[] = [];

    for (const frame of frames) {
      const instantMs = serviceMidnightMs + (frame.t_s as number) * 1000;
      const positions = positionsAt(dataset, instantMs, parityPolicy);
      const match = positions.find((position) => position.tripId === frame.trip_id);

      if (frame.present === false) {
        if (match) failures.push(`${frame.trip_id}@${frame.t_s}: expected absent, got present`);
        continue;
      }
      if (!match) {
        failures.push(`${frame.trip_id}@${frame.t_s}: expected present, got absent`);
        continue;
      }

      checked += 1;
      const deltaM = distanceM(
        match.lat,
        match.lon,
        frame.lat as number,
        frame.lon as number,
      );
      if (deltaM > LAT_LON_TOL_M) {
        failures.push(
          `${frame.trip_id}@${frame.t_s}: position off by ${deltaM.toFixed(2)} m`,
        );
      }
      if (Math.abs(match.sM - (frame.s_m as number)) > S_M_TOL_M) {
        failures.push(
          `${frame.trip_id}@${frame.t_s}: s_m ${match.sM.toFixed(2)} vs ${frame.s_m}`,
        );
      }
      if (Math.abs(match.speedKmh - (frame.speed_kmh as number)) > SPEED_TOL_KMH) {
        failures.push(
          `${frame.trip_id}@${frame.t_s}: speed ${match.speedKmh.toFixed(2)} vs ${frame.speed_kmh}`,
        );
      }
      if (match.status !== frame.status) {
        failures.push(`${frame.trip_id}@${frame.t_s}: status ${match.status} vs ${frame.status}`);
      }
      if (match.fromCode !== frame.from) {
        failures.push(`${frame.trip_id}@${frame.t_s}: from ${match.fromCode} vs ${frame.from}`);
      }
      if (match.toCode !== frame.to) {
        failures.push(`${frame.trip_id}@${frame.t_s}: to ${match.toCode} vs ${frame.to}`);
      }
      if (match.nextStopCode !== frame.next_stop) {
        failures.push(
          `${frame.trip_id}@${frame.t_s}: next stop ${match.nextStopCode} vs ${frame.next_stop}`,
        );
      }
      if (match.nextStopTime !== frame.next_stop_time) {
        failures.push(
          `${frame.trip_id}@${frame.t_s}: next time ${match.nextStopTime} vs ${frame.next_stop_time}`,
        );
      }
      if (failures.length > 20) break;
    }

    expect(failures.slice(0, 20)).toEqual([]);
    expect(checked).toBeGreaterThan(0);
  });
});
