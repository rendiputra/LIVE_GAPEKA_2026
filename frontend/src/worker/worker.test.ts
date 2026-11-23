/**
 * The worker's two guarantees, tested without a real Worker:
 *
 * 1. request coalescing must NEVER drop the LATEST requested instant, and
 * 2. the GeoJSON it posts must be `[lon, lat]` with the estimate flags intact.
 *
 * Both are pure, so they run in Node; the `positions.worker.ts` host is a thin
 * wiring layer over these.
 */
import { describe, expect, it } from "vitest";
import { createLatestRunner } from "./coalesce";
import { toPositionsGeoJSON } from "./geojson";
import type { TrainPosition } from "../engine/types";

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

describe("createLatestRunner", () => {
  it("processes a single submission", async () => {
    const seen: number[] = [];
    const runner = createLatestRunner<number>(async (value) => {
      seen.push(value);
    });
    runner.submit(1);
    await runner.whenIdle();
    expect(seen).toEqual([1]);
  });

  it("processes submissions in order when they arrive while idle", async () => {
    const seen: number[] = [];
    const runner = createLatestRunner<number>(async (value) => {
      seen.push(value);
    });
    runner.submit(1);
    await runner.whenIdle();
    runner.submit(2);
    await runner.whenIdle();
    expect(seen).toEqual([1, 2]);
  });

  it("never drops the latest instant when requests arrive during work", async () => {
    const gate = deferred();
    const seen: number[] = [];
    const runner = createLatestRunner<number>(async (value) => {
      seen.push(value);
      if (value === 1) await gate.promise;
    });

    runner.submit(1);
    // These all arrive while 1 is still being processed.
    runner.submit(2);
    runner.submit(3);
    runner.submit(4);
    gate.resolve();
    await runner.whenIdle();

    // Intermediate values may be coalesced away, but the newest must be computed.
    expect(seen[0]).toBe(1);
    expect(seen.at(-1)).toBe(4);
    expect(seen).toContain(4);
  });

  it("collapses a burst to at most two runs (current + latest)", async () => {
    const gate = deferred();
    const seen: number[] = [];
    const runner = createLatestRunner<number>(async (value) => {
      seen.push(value);
      if (value === 1) await gate.promise;
    });

    runner.submit(1);
    for (let value = 2; value <= 50; value += 1) runner.submit(value);
    gate.resolve();
    await runner.whenIdle();

    expect(seen).toHaveLength(2);
    expect(seen).toEqual([1, 50]);
  });

  it("keeps working after a processor throws", async () => {
    const seen: number[] = [];
    const runner = createLatestRunner<number>(async (value) => {
      seen.push(value);
      if (value === 1) throw new Error("boom");
    });

    runner.submit(1);
    await runner.whenIdle();
    runner.submit(2);
    await runner.whenIdle();

    expect(seen).toEqual([1, 2]);
  });

  it("resolves whenIdle immediately when nothing is queued", async () => {
    const runner = createLatestRunner<number>(async () => {});
    await expect(runner.whenIdle()).resolves.toBeUndefined();
  });

  it("accepts a new submission after going idle", async () => {
    const seen: number[] = [];
    const runner = createLatestRunner<number>(async (value) => {
      seen.push(value);
    });
    runner.submit(1);
    await runner.whenIdle();
    runner.submit(2);
    runner.submit(3);
    await runner.whenIdle();
    expect(seen.at(-1)).toBe(3);
  });
});

describe("toPositionsGeoJSON", () => {
  const position: TrainPosition = {
    tripId: "t1",
    trainNo: "50",
    name: "Gajayana",
    relation: "GMR-ML",
    lat: -6.2,
    lon: 106.8,
    bearing: 45,
    status: "running",
    sM: 1234.5,
    fromCode: "GMR",
    toCode: "MRI",
    nextStopCode: "MRI",
    nextStopTime: "08:20:00",
    speedKmh: 62.5,
    estimated: true,
    coarse: false,
    hasBypassedWaypoints: false,
    hasStraightLineSegment: false,
    serviceClass: "reguler",
    motionModel: "trapezoid_v1",
  };

  it("emits a FeatureCollection with Point features", () => {
    const collection = toPositionsGeoJSON([position]);
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.features).toHaveLength(1);
    expect(collection.features[0]!.geometry.type).toBe("Point");
  });

  it("orders coordinates as [lon, lat] (the classic GeoJSON bug)", () => {
    const [feature] = toPositionsGeoJSON([position]).features;
    expect(feature!.geometry.coordinates).toEqual([106.8, -6.2]);
  });

  it("carries the fields the marker and the detail panel need", () => {
    const [feature] = toPositionsGeoJSON([position]).features;
    const properties = feature!.properties;
    expect(properties.tripId).toBe("t1");
    expect(properties.trainNo).toBe("50");
    expect(properties.name).toBe("Gajayana");
    expect(properties.status).toBe("running");
    expect(properties.bearing).toBe(45);
    expect(properties.speedKmh).toBe(62.5);
    expect(properties.nextStopCode).toBe("MRI");
    expect(properties.nextStopTime).toBe("08:20:00");
  });

  it("keeps the estimate flags so a coarse trip stays labelled", () => {
    const coarse = { ...position, coarse: true, hasBypassedWaypoints: true };
    const [feature] = toPositionsGeoJSON([coarse]).features;
    expect(feature!.properties.coarse).toBe(true);
    expect(feature!.properties.hasBypassedWaypoints).toBe(true);
    expect(feature!.properties.estimated).toBe(true);
  });

  it("uses the trip id as the feature id so a client can diff markers", () => {
    const [feature] = toPositionsGeoJSON([position]).features;
    expect(feature!.id).toBe("t1");
  });

  it("handles an empty result", () => {
    expect(toPositionsGeoJSON([])).toEqual({ type: "FeatureCollection", features: [] });
  });
});
