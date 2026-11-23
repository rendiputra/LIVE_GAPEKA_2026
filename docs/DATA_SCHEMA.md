# DATA SCHEMA

Three layers, each with its own contract:

1. **SQLite** (`data/gapeka.db`, gitignored) — the pipeline's source of truth.
2. **Static export** (`web/public/data/`, gitignored) — what the browser reads.
3. **Python/TypeScript engine model** — what positions are computed from.

Schema changes require an ADR (`docs/decisions/`).

## 1. SQLite

`db/schema.sql` is authoritative. Tables:

| Table | Purpose |
|---|---|
| `gapeka_versions` | one row per Gapeka edition; `effective_from`, `pdf_sha256`, `status` |
| `stations` | code, printed `name`, human `official_name`, coordinate + `coord_status` + `coord_provenance` + `human_confirmed` |
| `station_coord_candidates` | every coordinate ever considered, including rejected ones (evidence is never deleted) |
| `trains` | `train_no`, `name`, `class`, `relation` |
| `trips` | one row per train per direction: `book`, `service_class`, `completeness`, `has_untimed_markers` |
| `stop_times` | the timetable: `arrive`, `depart`, `arrive_day_offset`, `depart_day_offset`, `day_offset_source`, `stop_type`, `time_source`, raw cells, `source_page` |
| `calendar` | `service_pattern` + `pattern_source` (ADR 002; the PDF states no weekday pattern) |
| `segments` | routed geometry per station pair: `geometry_quality`, `length_m`, `straight_m`, `detour_ratio` |
| `trip_geometry_status` | per trip: `status`, `has_bypassed_waypoints`, quality counts |
| `trip_waypoint_estimates` | one row per bypassed waypoint (`bypass_between_neighbours`) |
| `overrides` | generic patch table (documented, unused by the MVP build) |

Key enums:

- `stations.coord_status`: `accepted | override | rejected | missing` — only
  `accepted` and `override` reach geometry.
- `stations.coord_provenance`: `external_match | human_override |
  override_rule_approved`. A `decided_by` starting with `rule:` marks the third.
- `stations.human_confirmed`: 0/1, a human checked it on a map. Independent of
  provenance.
- `segments.geometry_quality`: `osm_routed | osm_routed_reviewed | osm_suspect |
  straight_line | unmeasured`.
- `trip_geometry_status.status`: `complete | complete_estimated | has_fallback |
  has_unmeasured`. `osm_routed_reviewed` counts as complete (ADR 005).
- `stop_times.day_offset_source`: `printed | derived_midnight_dwell` (ADR 007).

### Time model

All timetable times are **station-local WIB**, stored as `HH:MM:SS`, with the day
carried by `arrive_day_offset` / `depart_day_offset` (seconds of day alone cannot
represent a stop that arrives 23:58 and departs 00:03). A coordinate is rejected
unless it is inside Java and snaps within `snap_accept_m`.

## 2. Static export (`python -m pipeline.export_web`)

Deterministic, content-hashed, no timestamps. Files: `manifest.json`,
`stations.json`, `segments.json`, `trips.json` (plus `name.<hash>.json` aliases).

| File | Contents |
|---|---|
| `manifest.json` | `schema`, `version_name`, `effective_from`, `policy` defaults, `max_day_offset`, `content_hash`, `counts`, `attribution` |
| `stations.json` | `code`, `official_name`, `disambiguator`, `lat`, `lon` (null when there is no coordinate) |
| `segments.json` | one record per **unique** pair, polyline-encoded at precision 6, `length_m`, `quality` |
| `trips.json` | columnar per trip: `service_class`, `status`, `flags`, `hidden_by_default`, `first_s`, `last_s`, `segment_ids`, `reversed`, and `waypoints` columns (`code`, `s_m`, `arrive`, `depart`, `stop_type`, `bypassed`) |

Rules:

- Only `complete` and `complete_estimated` trips are exported. `has_unmeasured`
  never appears.
- Fakultatif trips are exported with `hidden_by_default: true`.
- A segment is stored **once**, in its canonical direction; the trip's direction
  is the `reversed` flag, applied at runtime.
- Bypassed rows are exported with `bypassed: 1` and inherit the previous known
  distance. They are display-only: the engine never builds a leg from them.
- `-1` means "no time" in the `arrive` / `depart` columns.

## 3. Engine model

Python (`engine/model.py`) and TypeScript (`web/src/engine/types.ts`) mirror each
other:

| Concept | Notes |
|---|---|
| `Policy` | `calendar_policy`, `show_fakultatif`, `enforce_effective_from`, `geometry_policy`, `accel_time_s`, `origin_lead_s`, `terminal_linger_s` |
| `Waypoint` | `station_code`, `arrive_sod` / `depart_sod`, both day offsets, cumulative `s_m`, `timed`, `bypassed` |
| `SegmentGeom` | oriented coordinates + cumulative distances; point lookup by bisect |
| `Trip` | waypoints, segments, `first_abs`, `last_abs`, flags (`coarse`, `has_bypassed_waypoints`, `has_straight_line_segment`) |
| `TrainPosition` | `lat`, `lon`, `bearing`, `status`, `s_m`, `from_code`, `to_code`, `next_stop_code/time`, `speed_kmh`, `estimated: true` |

Motion is `trapezoid_v1` (ADR 004): an ease phase only at `stop` ends, cruise
`v = L / (D - a_s/2 - a_e/2)`. This is an assumption, not Gapeka data, so every
position carries `estimated: true`.

Parity: `python -m pipeline.parity_frames` writes `engine/parity_frames.json`; the
TypeScript port must reproduce every frame within 1 m and 0.2 km/h. A mismatch is
a port bug, never a tolerance to widen.
