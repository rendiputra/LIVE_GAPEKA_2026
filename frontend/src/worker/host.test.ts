/**
 * The worker host: message protocol, snapshot lifecycle and coalescing, with
 * `postMessage` and the loader injected so it can be tested in Node.
 *
 * `positions.worker.ts` is only the `self.onmessage` wiring around this.
 */
import { describe, expect, it } from "vitest";
import { createWorkerHost, type WorkerRequest, type WorkerResponse } from "./host";
import { buildSnapshot } from "../engine/load";
import { readExportedBundle } from "../engine/testUtils";
import { DEFAULT_POLICY, type ScheduleSnapshot } from "../engine/types";

async function realSnapshot(): Promise<ScheduleSnapshot> {
  return buildSnapshot(await readExportedBundle());
}

function recorder() {
  const messages: WorkerResponse[] = [];
  return {
    messages,
    post: (message: WorkerResponse) => {
      messages.push(message);
    },
    ofType<T extends WorkerResponse["type"]>(type: T) {
      return messages.filter((message): message is Extract<WorkerResponse, { type: T }> =>
        message.type === type,
      );
    },
  };
}

describe("worker host: init", () => {
  it("loads the snapshot and announces readiness with the manifest facts", async () => {
    const out = recorder();
    const host = createWorkerHost({ loadSnapshot: realSnapshot, post: out.post });

    host.receive({ type: "init" });
    await host.whenIdle();

    const ready = out.ofType("ready");
    expect(ready).toHaveLength(1);
    expect(ready[0]!.versionName).toBe("Gapeka 2026");
    expect(ready[0]!.contentHash).toMatch(/^[0-9a-f]{16}$/);
    expect(ready[0]!.trips).toBe(625);
    expect(ready[0]!.segments).toBe(391);
    expect(ready[0]!.stations).toBe(389);
  });

  it("reports a load failure instead of hanging", async () => {
    const out = recorder();
    const host = createWorkerHost({
      loadSnapshot: async () => {
        throw new Error("network down");
      },
      post: out.post,
    });

    host.receive({ type: "init" });
    await host.whenIdle();

    const errors = out.ofType("error");
    expect(errors).toHaveLength(1);
    expect(errors[0]!.message).toContain("network down");
  });
});

describe("worker host: positions", () => {
  it("refuses a positions request before init", async () => {
    const out = recorder();
    const host = createWorkerHost({ loadSnapshot: realSnapshot, post: out.post });

    host.receive({ type: "positions", requestId: 1, instant: 0 });
    await host.whenIdle();

    const errors = out.ofType("error");
    expect(errors).toHaveLength(1);
    expect(errors[0]!.message).toMatch(/not ready/i);
    expect(errors[0]!.requestId).toBe(1);
  });

  it("answers with GeoJSON for the requested instant", async () => {
    const out = recorder();
    const host = createWorkerHost({ loadSnapshot: realSnapshot, post: out.post });
    host.receive({ type: "init" });
    await host.whenIdle();

    // 2026-12-01 08:00 WIB
    const instant = 1796058000000 + 8 * 3600 * 1000;
    host.receive({ type: "positions", requestId: 7, instant, policy: DEFAULT_POLICY });
    await host.whenIdle();

    const answers = out.ofType("positions");
    expect(answers).toHaveLength(1);
    expect(answers[0]!.requestId).toBe(7);
    expect(answers[0]!.geojson.type).toBe("FeatureCollection");
    expect(answers[0]!.geojson.features.length).toBe(answers[0]!.count);
    expect(answers[0]!.count).toBeGreaterThan(0);
  });

  it("coalesces a burst but always answers the LATEST instant", async () => {
    const out = recorder();
    const host = createWorkerHost({ loadSnapshot: realSnapshot, post: out.post });
    host.receive({ type: "init" });
    await host.whenIdle();

    const base = 1796058000000;
    for (let requestId = 1; requestId <= 20; requestId += 1) {
      host.receive({
        type: "positions",
        requestId,
        instant: base + requestId * 60_000,
        policy: DEFAULT_POLICY,
      });
    }
    await host.whenIdle();

    const answers = out.ofType("positions");
    expect(answers.length).toBeGreaterThanOrEqual(1);
    // The newest request must be answered; older ones may be superseded.
    expect(answers.at(-1)!.requestId).toBe(20);
  });

  it("handles a station board request", async () => {
    const out = recorder();
    const host = createWorkerHost({ loadSnapshot: realSnapshot, post: out.post });
    host.receive({ type: "init" });
    await host.whenIdle();

    host.receive({
      type: "board",
      requestId: 3,
      stationCode: "GMR",
      instant: 1796058000000 + 6 * 3600 * 1000,
      policy: DEFAULT_POLICY,
    });
    await host.whenIdle();

    const answers = out.ofType("board");
    expect(answers).toHaveLength(1);
    expect(answers[0]!.requestId).toBe(3);
    expect(answers[0]!.stationCode).toBe("GMR");
    expect(Array.isArray(answers[0]!.entries)).toBe(true);
    for (const entry of answers[0]!.entries) {
      expect(entry.stationCode).toBe("GMR");
    }
  });

  it("keeps serving after an unknown request type", async () => {
    const out = recorder();
    const host = createWorkerHost({ loadSnapshot: realSnapshot, post: out.post });
    host.receive({ type: "init" });
    await host.whenIdle();

    host.receive({ type: "nonsense" } as unknown as WorkerRequest);
    host.receive({ type: "positions", requestId: 9, instant: 1796058000000 + 8 * 3600 * 1000 });
    await host.whenIdle();

    expect(out.ofType("error").length).toBeGreaterThanOrEqual(1);
    expect(out.ofType("positions").at(-1)!.requestId).toBe(9);
  });
});
