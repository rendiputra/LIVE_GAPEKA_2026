/**
 * The worker host: protocol handling, snapshot lifecycle and request coalescing.
 *
 * `postMessage` and the snapshot loader are injected so this logic is testable
 * in Node; `positions.worker.ts` only wires `self.onmessage` to it.
 *
 * Coalescing contract: position requests are latest-wins. A superseded request
 * is NOT answered — the caller (the main-thread client) only awaits its own most
 * recent request, so an unanswered stale id is expected, not lost data. The
 * newest request is always answered.
 */
import { positionsAt } from "../engine/position";
import { stationBoard, type BoardEntry } from "../engine/queries";
import { createLatestRunner } from "./coalesce";
import { toPositionsGeoJSON, type PositionsFeatureCollection } from "./geojson";
import type { Policy, ScheduleSnapshot } from "../engine/types";
import { DEFAULT_POLICY } from "../engine/types";

export type WorkerRequest =
  | { readonly type: "init" }
  | {
      readonly type: "positions";
      readonly requestId: number;
      readonly instant: number;
      readonly policy?: Policy;
    }
  | {
      readonly type: "board";
      readonly requestId: number;
      readonly stationCode: string;
      readonly instant: number;
      readonly policy?: Policy;
    };

export type WorkerResponse =
  | {
      readonly type: "ready";
      readonly versionName: string;
      readonly effectiveFrom: string;
      readonly effectiveTo: string | null;
      readonly contentHash: string;
      readonly maxDayOffset: number;
      readonly trips: number;
      readonly segments: number;
      readonly stations: number;
      readonly attribution: ScheduleSnapshot["attribution"];
    }
  | {
      readonly type: "positions";
      readonly requestId: number;
      readonly instant: number;
      readonly count: number;
      readonly geojson: PositionsFeatureCollection;
    }
  | {
      readonly type: "board";
      readonly requestId: number;
      readonly stationCode: string;
      readonly instant: number;
      readonly entries: readonly BoardEntry[];
    }
  | {
      readonly type: "error";
      readonly requestId?: number;
      readonly message: string;
    };

export interface WorkerHostDeps {
  readonly loadSnapshot: () => Promise<ScheduleSnapshot>;
  readonly post: (message: WorkerResponse) => void;
}

export interface WorkerHost {
  receive(request: WorkerRequest): void;
  whenIdle(): Promise<void>;
}

export function createWorkerHost(deps: WorkerHostDeps): WorkerHost {
  let snapshot: ScheduleSnapshot | null = null;
  let initialising: Promise<void> | null = null;

  const announceReady = (loaded: ScheduleSnapshot): void => {
    const segmentKeys = new Set<string>();
    for (const trip of loaded.trips) {
      for (const segment of trip.segments) {
        const [a, b] = [segment.fromCode, segment.toCode].sort();
        segmentKeys.add(`${a}|${b}`);
      }
    }
    deps.post({
      type: "ready",
      versionName: loaded.versionName,
      effectiveFrom: loaded.effectiveFrom,
      effectiveTo: loaded.effectiveTo,
      contentHash: loaded.contentHash,
      maxDayOffset: loaded.maxDayOffset,
      trips: loaded.trips.length,
      segments: segmentKeys.size,
      stations: loaded.stations.size,
      attribution: loaded.attribution,
    });
  };

  const runner = createLatestRunner<WorkerRequest>(async (request) => {
    if (request.type === "positions") {
      if (snapshot === null) {
        deps.post({ type: "error", requestId: request.requestId, message: "worker not ready" });
        return;
      }
      const positions = positionsAt(
        snapshot,
        request.instant,
        request.policy ?? snapshot.policy,
      );
      const geojson = toPositionsGeoJSON(positions);
      deps.post({
        type: "positions",
        requestId: request.requestId,
        instant: request.instant,
        count: positions.length,
        geojson,
      });
      return;
    }

    if (request.type === "board") {
      if (snapshot === null) {
        deps.post({ type: "error", requestId: request.requestId, message: "worker not ready" });
        return;
      }
      deps.post({
        type: "board",
        requestId: request.requestId,
        stationCode: request.stationCode,
        instant: request.instant,
        entries: stationBoard(
          snapshot,
          request.stationCode,
          request.instant,
          request.policy ?? snapshot.policy,
        ),
      });
      return;
    }

    deps.post({ type: "error", message: `unknown request: ${String((request as { type: string }).type)}` });
  });

  const loadOnce = (): Promise<void> => {
    if (initialising === null) {
      initialising = deps
        .loadSnapshot()
        .then((loaded) => {
          snapshot = loaded;
          announceReady(loaded);
        })
        .catch((error: unknown) => {
          initialising = null;
          deps.post({ type: "error", message: String(error) });
        });
    }
    return initialising;
  };

  return {
    receive(request: WorkerRequest): void {
      if (request.type === "init") {
        void loadOnce();
        return;
      }
      // A consumer that never called init gets a clear error rather than a
      // surprise network load: the snapshot lifecycle stays explicit.
      runner.submit(request);
    },
    whenIdle(): Promise<void> {
      return (initialising ?? Promise.resolve()).then(() => runner.whenIdle());
    },
  };
}

/** Policy used when a request omits one; mirrors the engine defaults. */
export const WORKER_DEFAULT_POLICY = DEFAULT_POLICY;
