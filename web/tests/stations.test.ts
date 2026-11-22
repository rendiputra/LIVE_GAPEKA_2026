// T4: stations without coordinates (STM, TPR, CIK) must not break the UI.
//
// They appear in stop lists and in station search, but cannot be placed on the
// map. The data layer must expose them with lat/lon null and a usable name, and
// the stop-list rendering must not depend on coordinates.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { prepare, positionsAt, pointOnTrip } from "../src/engine/position";
import type { Manifest, Policy } from "../src/engine/types";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const DATA = resolve(ROOT, "web/public/data");

const manifest: Manifest = JSON.parse(readFileSync(resolve(DATA, "manifest.json"), "utf8"));
const stationsPayload = JSON.parse(readFileSync(resolve(DATA, "stations.json"), "utf8"));
const segmentsPayload = JSON.parse(readFileSync(resolve(DATA, "segments.json"), "utf8"));
const tripsPayload = JSON.parse(readFileSync(resolve(DATA, "trips.json"), "utf8"));

const dataset = prepare(
  manifest,
  stationsPayload.stations,
  segmentsPayload.segments,
  tripsPayload.trips,
  tripsPayload.stop_types,
);

const policy: Policy = {
  showFakultatif: false,
  enforceEffectiveFrom: false,
  accelTimeS: manifest.policy.accel_time_s,
  terminalLingerS: manifest.policy.terminal_linger_s,
};

const COORDLESS = ["STM", "TPR", "CIK"];

describe("stations without coordinates", () => {
  it("are present in the export with null lat/lon", () => {
    for (const code of COORDLESS) {
      const station = dataset.stationByCode.get(code);
      expect(station, code).toBeDefined();
      expect(station?.lat, code).toBeNull();
      expect(station?.lon, code).toBeNull();
    }
  });

  it("still have a usable display name", () => {
    for (const code of COORDLESS) {
      const station = dataset.stationByCode.get(code);
      const name = station?.disambiguator
        ? `${station.official_name} (${station.disambiguator})`
        : station?.official_name;
      expect(name, code).toBeTruthy();
      expect(name, code).not.toBe(code);
    }
  });

  it("appear in trip waypoints without breaking the engine", () => {
    let found = 0;
    for (const trip of dataset.trips) {
      for (const waypoint of trip.waypoints) {
        if (COORDLESS.includes(waypoint.stationCode)) found += 1;
      }
    }
    expect(found).toBeGreaterThan(0);
  });

  it("does not prevent positions from being computed", () => {
    // 2026-12-01 09:00 WIB
    const instant = Date.UTC(2026, 11, 1, 9, 0, 0) - 7 * 3600 * 1000;
    const positions = positionsAt(dataset, instant, policy);
    expect(positions.length).toBeGreaterThan(0);
    for (const position of positions) {
      expect(Number.isFinite(position.lat)).toBe(true);
      expect(Number.isFinite(position.lon)).toBe(true);
    }
  });

  it("keeps every position on its own polyline", () => {
    const instant = Date.UTC(2026, 11, 1, 9, 0, 0) - 7 * 3600 * 1000;
    for (const position of positionsAt(dataset, instant, policy)) {
      const trip = dataset.trips.find((candidate) => candidate.data.trip_id === position.tripId);
      expect(trip).toBeDefined();
      const [lat, lon] = pointOnTrip(trip!, position.sM);
      expect(Math.abs(lat - position.lat)).toBeLessThan(1e-9);
      expect(Math.abs(lon - position.lon)).toBeLessThan(1e-9);
    }
  });
});
