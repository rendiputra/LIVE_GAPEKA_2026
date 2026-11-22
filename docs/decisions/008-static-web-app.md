# ADR 008 — Static web app with positions computed in the browser

- Status: accepted (Phase 6a)
- Date: 2026-11-22
- Context: how to ship the map without a server

> The task referred to this as ADR 007, but 007 is already "Separate
> arrive/depart day offsets". ADRs are append-only, so this one is 008.

## Decision

Phase 6 ships a **static site**. There is no FastAPI, no database at the edge, and
no request-time computation on a server.

- The Python pipeline exports a compact schedule (`python -m pipeline.export_web`)
  into `web/public/data/`, content-hashed, deterministic, no timestamps.
- The browser computes positions from that export in a Web Worker, using a
  TypeScript port of `engine/position.py` (`trapezoid_v1`, service-date scan,
  policy flags).
- The Python engine stays the **reference implementation**. The port must match
  it on `engine/parity_frames.json`; a mismatch is a bug, never a tolerance.

## Why

- The load is spiky (long weekends, holidays). A static file is cached by the CDN
  and costs nothing per user; a server would need to scale for a few peak days.
- The schedule is static between Gapeka revisions. Serving it once and computing
  locally is the same answer for everyone.
- Offline-ish behaviour and instant replay become trivial: replay is just another
  timestamp.
- Hard Rule 3 wants a pure estimator. Running the same pure function in the
  browser keeps that property instead of wrapping it in an API.

## Consequences

- The export is public data. It contains no personal data and no secrets.
- A Gapeka revision means re-exporting and re-deploying, not a DB migration.
- The TypeScript port is a second implementation and must be kept in parity by
  tests; `parity_frames.json` is the contract.
- Tile hosting becomes the only runtime dependency (see `docs/DEPLOY.md`).
- If real-time data ever arrives, it needs a small service; the UI already
  separates "estimated" from any future "live" source.

## Alternatives considered

- **FastAPI in Phase 6** (the original AGENTS plan). Rejected for the MVP: it adds
  a running service, a cache and a deployment target for a static answer.
- **Precompute every 30 s frame for a year.** Rejected: hundreds of MB, and it
  cannot answer an arbitrary instant.
- **Server-side rendering of the map.** Rejected: no benefit for a small static
  data set.
