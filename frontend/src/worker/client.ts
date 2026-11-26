/**
 * The React side of the worker protocol.
 *
 * The worker evaluates positions off the main thread; this hook only patches the
 * store with the RESULTS. `trainsSource` etc. are deliberately not here — those
 * are written straight into MapLibre by the loop.
 */
import { useCallback, useEffect, useRef } from "react";
import type { PositionsFeatureCollection } from "./geojson";
import type { Policy } from "../engine/types";
import type { WorkerRequest, WorkerResponse } from "./host";

export interface WorkerClient {
  readonly requestPositions: (instant: number, policy?: Policy) => void;
  readonly requestBoard: (
    stationCode: string,
    instant: number,
    policy?: Policy,
  ) => void;
  readonly init: (dataBaseUrl?: string) => void;
}

export interface WorkerClientHandlers {
  readonly onReady: (response: Extract<WorkerResponse, { type: "ready" }>) => void;
  readonly onPositions: (
    response: Extract<WorkerResponse, { type: "positions" }>,
  ) => void;
  readonly onBoard: (response: Extract<WorkerResponse, { type: "board" }>) => void;
  readonly onError: (response: Extract<WorkerResponse, { type: "error" }>) => void;
}

function workerUrl(): string {
  return new URL("./positions.worker.ts", import.meta.url).toString();
}

export function createWorker(): Worker {
  return new Worker(workerUrl(), { type: "module" });
}

/**
 * Create a worker client with the latest-request guard. A response for a
 * superseded request id is ignored, which is what makes the worker's
 * latest-wins coalescing safe on the main thread.
 */
export function createWorkerClient(
  worker: Pick<
    Worker,
    "postMessage" | "addEventListener" | "removeEventListener" | "terminate"
  >,
  handlers: WorkerClientHandlers,
): { client: WorkerClient; latest: () => number } {
  let requestId = 0;
  const latestId: { current: number } = { current: 0 };

  const dispatch = (response: WorkerResponse): void => {
    switch (response.type) {
      case "ready":
        handlers.onReady(response);
        return;
      case "positions":
        if (response.requestId !== latestId.current) return;
        handlers.onPositions(response);
        return;
      case "board":
        if (response.requestId !== latestId.current) return;
        handlers.onBoard(response);
        return;
      case "error":
        handlers.onError(response);
        return;
      default:
        return;
    }
  };

  const onMessage = (event: MessageEvent<WorkerResponse>): void => {
    dispatch(event.data);
  };
  worker.addEventListener("message", onMessage as EventListener);

  const send = (request: WorkerRequest): void => {
    worker.postMessage(request);
  };

  const client: WorkerClient = {
    init: (dataBaseUrl?: string) =>
      send(dataBaseUrl === undefined ? { type: "init" } : { type: "init", dataBaseUrl }),
    requestPositions: (instant, policy) => {
      requestId += 1;
      latestId.current = requestId;
      send(
        policy === undefined
          ? { type: "positions", requestId, instant }
          : { type: "positions", requestId, instant, policy },
      );
    },
    requestBoard: (stationCode, instant, policy) => {
      requestId += 1;
      latestId.current = requestId;
      send(
        policy === undefined
          ? { type: "board", requestId, stationCode, instant }
          : { type: "board", requestId, stationCode, instant, policy },
      );
    },
  };

  return { client, latest: () => latestId.current };
}

/** React hook wrapper: owns the worker for the component's lifetime. */
export function useWorker(handlers: WorkerClientHandlers): WorkerClient | null {
  const workerRef = useRef<Worker | null>(null);
  const clientRef = useRef<WorkerClient | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const worker = createWorker();
    workerRef.current = worker;
    const { client } = createWorkerClient(worker, {
      onReady: (response) => handlersRef.current.onReady(response),
      onPositions: (response) => handlersRef.current.onPositions(response),
      onBoard: (response) => handlersRef.current.onBoard(response),
      onError: (response) => handlersRef.current.onError(response),
    });
    clientRef.current = client;
    client.init();
    return () => {
      worker.terminate();
      workerRef.current = null;
      clientRef.current = null;
    };
  }, []);

  const requestPositions = useCallback((instant: number, policy?: Policy) => {
    clientRef.current?.requestPositions(instant, policy);
  }, []);
  const requestBoard = useCallback(
    (stationCode: string, instant: number, policy?: Policy) => {
      clientRef.current?.requestBoard(stationCode, instant, policy);
    },
    [],
  );
  const init = useCallback(() => clientRef.current?.init(), []);

  return { requestPositions, requestBoard, init };
}

export type { PositionsFeatureCollection, Policy };
