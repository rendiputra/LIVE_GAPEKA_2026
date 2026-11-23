/// <reference lib="webworker" />
/**
 * The Web Worker entry point.
 *
 * Everything substantive lives in `host.ts` (protocol + coalescing),
 * `fetchSchedule.ts` (network + parse) and `engine/` (pure maths), all of which
 * are tested in Node. This file only adapts the worker global scope.
 *
 * Loading, JSON parsing and polyline decoding all happen here, off the main
 * thread, so the first paint never blocks on a 1.1 MB payload.
 */
import { createWorkerHost, type WorkerRequest, type WorkerResponse } from "./host";
import { fetchSnapshot } from "./fetchSchedule";

/** `public/data` is served from the app root; Vite rewrites BASE_URL on deploy. */
const BASE_URL = `${import.meta.env.BASE_URL.replace(/\/+$/, "")}/data`;

interface WorkerScope {
  postMessage(message: WorkerResponse): void;
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
}

const scope = self as unknown as WorkerScope;

const host = createWorkerHost({
  loadSnapshot: () => fetchSnapshot(BASE_URL),
  post: (message) => scope.postMessage(message),
});

scope.onmessage = (event: MessageEvent<WorkerRequest>) => {
  host.receive(event.data);
};
