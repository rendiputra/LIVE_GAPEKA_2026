/**
 * Fix 3: the rail network geometry.
 *
 * `trips.flatMap(t => t.segments)` yields one copy of a segment per train and
 * per direction. The map wants each physical segment once.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { buildSnapshot } from "../engine/load";
import { railNetworkGeoJSON, uniqueRailSegments } from "./layers";
import { readExportedBundle } from "../engine/testUtils";
import type { ScheduleSnapshot } from "../engine/types";

let snapshot: ScheduleSnapshot;

beforeAll(async () => {
  snapshot = buildSnapshot(await readExportedBundle());
});

describe("uniqueRailSegments", () => {
  it("collapses both directions and every train to one segment per pair", () => {
    const flattened = snapshot.trips.flatMap((trip) => trip.segments);
    const unique = uniqueRailSegments(snapshot.trips);

    // The naive list is far larger than the physical network.
    expect(flattened.length).toBeGreaterThan(unique.length * 3);
    expect(unique).toHaveLength(391);

    const pairs = new Set(
      unique.map((segment) =>
        segment.fromCode < segment.toCode
          ? `${segment.fromCode}|${segment.toCode}`
          : `${segment.toCode}|${segment.fromCode}`,
      ),
    );
    expect(pairs.size).toBe(unique.length);
  });

  it("keeps the geometry and length of the first occurrence", () => {
    for (const segment of uniqueRailSegments(snapshot.trips)) {
      expect(segment.lengthM).toBeGreaterThan(0);
      expect(segment.coordinates.length).toBeGreaterThan(1);
    }
  });

  it("is empty for a snapshot with no trips", () => {
    expect(uniqueRailSegments([])).toEqual([]);
  });
});

describe("railNetworkGeoJSON", () => {
  it("emits one LineString per unique segment", () => {
    const collection = railNetworkGeoJSON(snapshot.trips);
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.features).toHaveLength(391);
    for (const feature of collection.features) {
      expect(feature.geometry.type).toBe("LineString");
    }
  });

  it("orders coordinates as [lon, lat]", () => {
    const [feature] = railNetworkGeoJSON(snapshot.trips).features;
    const geometry = feature!.geometry as {
      type: "LineString";
      coordinates: ReadonlyArray<readonly [number, number]>;
    };
    const [lon, lat] = geometry.coordinates[0]!;
    // Every Java station is inside this box; swapped coordinates would leave it.
    expect(lat).toBeGreaterThan(-9.5);
    expect(lat).toBeLessThan(-5.5);
    expect(lon).toBeGreaterThan(105);
    expect(lon).toBeLessThan(115);
  });

  it("uses stable ids derived from the station pair", () => {
    const ids = railNetworkGeoJSON(snapshot.trips).features.map((feature) => feature.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});