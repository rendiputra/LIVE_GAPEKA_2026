# ADR 005 — Human segment reviews turn a suspect route into a reviewed one

- Status: accepted (Phase 5b)
- Date: 2026-11-22
- Context: `osm_suspect` is a flag, not a verdict

## Context

`build_geometry` marks a routed segment `osm_suspect` when the routed length
exceeds the straight-line length by more than `detour_suspect_ratio` (1.6). That
test is deliberately blunt, and the Phase 5b review showed both failure modes:

- **The route is right.** `CA-PWK` routes 6.634 km against 2.903 km straight
  (ratio 2.285). Routing from every other nearby track gives 6.594 km (ratio
  2.272), so the detour is a property of the line, not of the chosen track.
- **The route is wrong.** `BTT-CS` routes 11.544 km against 4.259 km straight
  (ratio 2.711), but routing from the adjacent way gives 4.949 km (ratio 1.162).
  The cause is the nearest-edge snap picking a stub, not a missing way.

A validator cannot tell these apart, and it must not guess. Only a human can
decide, so the decision needs a place to live.

## Decision

A human-authored file, `data/config/segment_reviews.yaml`, records a decision per
segment:

```yaml
reviews:
  - from: "CA"
    to: "PWK"
    decision: "accept_route"
    reason: "the line really does loop here"
    decided_by: "human"
    date: "2026-11-22"
```

- `accept_route` — the quality becomes **`osm_routed_reviewed`**, which counts as
  **complete** for `trip_geometry_status`. The detour ratio and the original
  reason are still reported.
- `needs_bridge` — the segment stays `osm_suspect` and keeps the trip out of the
  default view.
- A review on a segment that was not suspect is **ignored and reported**; it
  never silently changes a clean route.
- The pipeline never writes this file. It only reads it.

`osm_routed_reviewed` is a distinct quality, not a rewrite of `osm_routed`, so a
reviewed route stays distinguishable from a route that never needed review.

## Consequences

- The set of `osm_suspect` segments can only shrink through human decisions.
- A reviewed segment is still visible with its real numbers; nothing is hidden.
- The browser and the API must accept `osm_routed_reviewed` wherever they accept
  `osm_routed`.
- The file is committed (it is a decision record), unlike `station_overrides.yaml`
  which is gitignored and local to a human's machine.

## Alternatives considered

- **Raise `detour_suspect_ratio`.** Rejected: it would hide genuine failures too,
  and the threshold is already 1.6.
- **Auto-accept when the best alternative track gives nearly the same distance.**
  Rejected: that is a rule, not a human decision, and it would still be wrong for
  a line whose OSM data is incomplete in a way no local test reveals.
- **Treat `osm_suspect` as complete.** Rejected: it discards a real signal.
