// Positions run in a worker so the map stays smooth (B4). The worker loads the
// static export once and answers one question: "who is moving at this instant?".

import { prepare, positionsAt, type Dataset, type TrainPosition } from "../engine/position";
import type { Manifest, Policy } from "../engine/types";

interface InitMessage {
  type: "init";
  base: string;
}

interface QueryMessage {
  type: "query";
  id: number;
  instantMs: number;
  policy: Policy;
}

type Incoming = InitMessage | QueryMessage;

let dataset: Dataset | null = null;
let ready: Promise<void> | null = null;

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return (await response.json()) as T;
}

async function init(base: string): Promise<void> {
  const manifest = await fetchJson<Manifest>(`${base}/manifest.json`);
  const stations = await fetchJson<{ stations: Dataset["stations"] }>(`${base}/stations.json`);
  const segments = await fetchJson<{ segments: Dataset["segments"] }>(`${base}/segments.json`);
  const trips = await fetchJson<{
    trips: Parameters<typeof prepare>[3];
    stop_types: string[];
  }>(`${base}/trips.json`);
  dataset = prepare(
    manifest,
    stations.stations,
    segments.segments,
    trips.trips,
    trips.stop_types,
  );
}

self.onmessage = (event: MessageEvent<Incoming>) => {
  const message = event.data;
  if (message.type === "init") {
    ready = init(message.base);
    ready
      .then(() => self.postMessage({ type: "ready" }))
      .catch((error: Error) => self.postMessage({ type: "error", error: String(error) }));
    return;
  }
  if (message.type === "query") {
    const id = message.id;
    const instantMs = message.instantMs;
    const policy = message.policy;
    void (ready ?? Promise.resolve())
      .then(() => {
        if (!dataset) throw new Error("dataset not loaded");
        const positions: TrainPosition[] = positionsAt(dataset, instantMs, policy);
        self.postMessage({ type: "result", id, positions });
      })
      .catch((error: Error) =>
        self.postMessage({ type: "error", id, error: String(error) }),
      );
  }
};
