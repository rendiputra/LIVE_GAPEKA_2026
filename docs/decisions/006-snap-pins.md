# ADR 006 — Snap pins (and why routing-aware snapping is not the default)

- Status: accepted (Phase 5c)
- Date: 2026-11-22
- Context: a station between two tracks, and `BTT-CS`

## Context

`build_geometry` snaps a station to the **geometrically nearest** rail edge. On a
double-track line a station is within a few metres of both tracks, and the nearest
one can be a stub whose only connection is far away. Two concrete cases:

- **TLM**: nearest edge (way 1154169186, 20.6 m) routes 12.4 km to its neighbours;
  way 1311188691 (23.7 m) routes 6.9 km. Rail-path triple 1.794 vs 1.000.
- **BTT**: nearest edge (way 163744589, 5.4 m) routes `BTT-CS` 11.544 km; way
  163741924 (9.8 m) routes 4.953 km.

The coordinate is correct in both cases. The *track choice* is wrong, and no
coordinate override can fix it.

## Decision

A human-authored pin file, `data/config/snap_pins.yaml`, names the way:

```yaml
pins:
  - station: "TLM"
    way_id: 1311188691
    reason: "..."
    evidence: "..."
    decided_by: "human"
    date: "2026-11-22"
```

- A pinned station snaps to the nearest point on that way, splitting it as usual.
- If the station is farther than `snap_accept_m` from the pinned way the pin is
  **not** honoured: the normal snap is used and the pin is reported as unusable,
  so a stale pin can never move a station silently.
- The pipeline never writes the file.

## Routing-aware snapping: experiment, not default

An experiment chose, per station, the edge minimising the routed distance to its
neighbours (`python -m pipeline.snap_experiment`). Result:

- 382 stations evaluated, 23 changed, 3 reverted by a guard because they made a
  neighbour's segment worse;
- 13 segments changed by more than 0.5 %, **all shorter, none longer**;
- the four pilot trips moved by at most 0.18 %;
- it independently reproduces **both** pins (TLM and BTT).

It is not the default for three reasons:

1. It is self-referential: it optimises the same distances it is judged by, so it
   can hide a genuinely wrong coordinate by choosing whichever track makes the
   route look plausible.
2. Without the guard it made four segments **longer**, including both pinned
   ones. The guard is a heuristic, not a proof.
3. A pin states a fact a human checked on a map; an optimiser states a preference.

## Consequences

- `snap_bands` gains `ok_pinned`, so a pinned station is never invisible.
- Pins are tracked in git with the other human config.
- A pin that becomes stale is reported, not applied.
