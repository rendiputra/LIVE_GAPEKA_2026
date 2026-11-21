# ADR 004 — Trapezoidal motion model and engine policy defaults

- Status: accepted (Phase 5)
- Date: 2026-11-22
- Context: the position engine needs a speed profile between timed waypoints

## Context

The Gapeka states when a train arrives at and departs from each station. It says
nothing about how the train moves between them. Any position between two timed
rows is therefore an **estimate**, and the estimate needs an explicit, documented
model rather than an implicit assumption.

## Decision

### Motion (`motion_model = "trapezoid_v1"`)

Between consecutive TIMED waypoints `i -> j`:

- `D = T_j - T_i`, `L = S_j - S_i`;
- an end receives an acceleration/deceleration phase **only if that row is a
  `stop`** (the train is at rest). A `pass` row gets none;
- `a_s = min(accel_time_s, D/3)`, `a_e` likewise;
- cruise speed `v = L / (D - a_s/2 - a_e/2)`;
- the profile is quadratic (eased start), linear (cruise), quadratic (eased end),
  and reaches exactly `S_j` at `T_j`.

`accel_time_s` defaults to **60 s**. The 24-hour sweep compares each leg's cruise
speed with the PDF's printed `Kecepatan Maksimum`: 9,333 of 9,379 legs are at or
below it, 13 are more than 10% above (mostly `MSG <-> BTT`, printed 50 km/h).
Those are reported as V13 evidence and left uncorrected; 60 s is not forcing
implausible speeds across the network.

This is an **assumption**, not data from the Gapeka. Every output carries
`motion_model` and `estimated = true`.

### Policy defaults

| Field | Default | Meaning |
|---|---|---|
| `calendar_policy` | `regular_daily_assumed` | reguler = every day (ADR 002); fakultatif hidden |
| `show_fakultatif` | `false` | fakultatif and unknown classes are hidden |
| `enforce_effective_from` | `false` | development may preview before 2026-12-01 |
| `geometry_policy` | `complete_and_estimated` | also `complete_only`, `allow_fallback` |
| `accel_time_s` | `60` | ease duration cap |
| `origin_lead_s` | `0` | no invented pre-departure motion |
| `terminal_linger_s` | `0` | train disappears at its last arrival |

### Geometry policy

- `complete` and `complete_estimated` are shown by default;
- `allow_fallback` additionally shows `has_fallback` trips, flagged;
- `has_unmeasured` is **never** shown, under any policy.

## Consequences

- A `pass` waypoint has no dwell, so a train never appears stopped there.
- Two trains on the same segment with the same schedule produce the same
  positions; that is correct, since the estimate depends only on the timetable.
- If real acceleration data ever becomes available, only `accel_time_s` and
  `profile.py` change; the rest of the engine is unaffected.
- The browser port must reproduce `trapezoid_v1` exactly, verified against
  `engine/golden_frames.json`.

## Alternatives considered

- **Constant speed between stops.** Rejected: it makes a train jump from 0 to
  cruise instantly at a station, which looks wrong on a map.
- **Realistic acceleration curves per rolling stock.** Rejected: no such data in
  the PDF, and inventing it would violate Hard Rule 1.
- **Interpolate by distance only.** Rejected: it ignores the timetable, which is
  the only real input we have.
