# ADR 011 — Positions are computed in a Web Worker with latest-wins coalescing

- Status: accepted (frontend revamp, Turn 1)
- Date: 2026-11-23
- Context: where the per-frame position computation runs, and what happens when requests outpace it

## Context

The exported schedule is ~1.1 MB raw (~264 kB gzip): 625 trips, 391 polylines and
389 stations. Decoding 391 polylines and running `positions_at` produces hundreds
of positions per call. A map that animates train markers asks for a new instant
roughly every frame.

ADR 008 already decided the browser computes positions from static data. It did
not say where. Two things can go wrong on the main thread:

1. **First paint blocks** on fetching, parsing and decoding the payload.
2. **Requests pile up.** If the computation is slower than the request rate, a
   naive queue makes the map lag further and further behind, and the user ends up
   looking at a position from several seconds ago.

## Decision

1. **The worker owns loading and computation.** Fetch, `JSON.parse`, polyline
   decoding, `positions_at`, station boards and the GeoJSON conversion all run in
   `positions.worker.ts`. The main thread receives ready-to-render GeoJSON.
2. **The protocol is explicit and typed.** `init`, `positions`, `board` requests;
   `ready`, `positions`, `board`, `error` responses. Every response carries the
   request id, so a client can discard a reply it no longer wants.
3. **Coalescing is latest-wins, and the newest request is never dropped.** While a
   computation is in flight, at most one pending request is retained and it is
   always the most recent. A burst of 50 frames therefore costs at most two
   computations: the one running and the newest.
4. **A superseded request is not answered.** The client only awaits its own most
   recent request, so this is not lost work — it is the mechanism. Sending an
   answer for every stale id would recreate the queue the design exists to avoid.
5. **`init` is explicit.** A `positions` or `board` request before `init` gets a
   `worker not ready` error instead of triggering an implicit network load, so the
   snapshot lifecycle stays visible and testable.
6. **The engine stays pure and testable outside the worker.** `src/engine/` has no
   DOM and no fetch; `host.ts` takes `post` and the loader as parameters. The
   worker entry file is a thin adapter, so every guarantee above is tested in Node
   without a real `Worker`.

## Why

- **No jank.** A 1.1 MB parse plus 391 polyline decodes on the main thread is a
  visible stall; off-thread it is invisible.
- **Correct lag, not accumulating lag.** Latest-wins bounds the work per request
  burst. A bounded queue would still drift; an unbounded one drifts forever.
- **The failure mode is chosen deliberately.** The alternative — dropping the
  newest request — is the only unacceptable option, because it means the map shows
  a time the user did not ask for and never catches up.
- **Testable without a browser.** The parity gate and the coalescing tests run in
  Vitest in about 2.5 s, which is what makes them run at all.

## Consequences

- The main thread must tolerate never receiving a reply for a superseded id. The
  client wrapper (Turn 3) tracks only its latest request id.
- State is snapshot-scoped: re-initialising means a new worker or a reload. A
  future live-reload of the schedule is a new decision.
- The GeoJSON payload crosses the thread boundary every frame. This is cheap
  (structured clone of a few hundred small objects) compared with recomputing, and
  it keeps the main thread free of engine code entirely.
- Browser-only APIs (`fetch`, worker scope) are confined to two small adapter
  files, so the engine can still be exercised in Node and in the parity gate.

## Alternatives considered

- **Compute on the main thread.** Rejected: blocks paint and makes the parity gate
  harder to run headless.
- **Server-side positions (the deferred FastAPI plan).** Rejected for the MVP by
  ADR 008: a static site has no server, and per-request compute for 500+ trains
  during a holiday peak is exactly the load the static design avoids.
- **A queue that answers every request.** Rejected: it produces the unbounded lag
  this ADR exists to prevent.
- **Dropping the newest request while busy.** Rejected: it strands the map at a
  stale instant, the one failure a user notices immediately.
- **`SharedArrayBuffer` + transferables.** Not warranted: the payload is small and
  the cross-thread copy is not the bottleneck. It would also require COOP/COEP
  headers, which a plain static host does not set.