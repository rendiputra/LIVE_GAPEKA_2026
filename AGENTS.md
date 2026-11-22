# AGENTS.md — Gapeka-Based Train Position Estimator

> Works with Claude Code (copy or symlink to `CLAUDE.md`), Codex, Cursor, etc.
> Read this entire file before writing any code. Work on **one phase per session**, in order.

## 1. Goal

Convert the Indonesian railway timetable PDF **Gapeka 2026** into a map website that shows **estimated train positions based on the schedule** (NOT actual positions).

### 1.1 Source document (verified 2026-11-19)

| Fact | Value |
|---|---|
| File | `data/input/GAPEKA_2026.pdf` (gitignored, never committed) |
| SHA-256 | `5149c60ca7a739081bf32e13779bd574f89f2e4665fb5e2b1dcda247899710a4` |
| Size | 61,479,133 bytes (58.6 MiB) |
| Pages | **1,887** |
| Text | selectable on 1,875 pages; **12 pages are image-only** (1-5, 1676, 1702, 1707, 1740, 1776, 1813, 1819) — none contain timetable data |
| Scope | **Java only** — the document is titled "Jaringan Jalur Kereta Api Nasional **di Jawa**" |

Document map (approximate, from sampling; the generated ranges are in `docs/inventory_report.md`):

| PDF pages | Content |
|---|---|
| 1-5 | Image-only cover and ministerial decree |
| 6-51 | Lampiran I — stringline charts (Grafik Perjalanan KA) |
| 52-811 | Lampiran II book 1+2 — intercity/regional timetables |
| 812-1513 | Lampiran II — KRL/commuter timetables |
| 1514-1673 | Lampiran II — freight (KA barang) timetables |
| 1674-1824 | Lampiran III — rolling stock, seat maps, capacity diagrams |
| 1825-1864 | Lampiran IV — train numbering, classification, travel-time summary |
| 1865-1887 | Capacity and inter-station distance annexes |

### 1.2 Scope priority

- **MVP = the intercity/regional section (approx. PDF 52-811).**
- The **KRL section (approx. 812-1513) comes after the MVP**, as a separate
  sub-phase: different header format, two trains per page, and an unreliable
  text-stream order.
- The **freight section (approx. 1514-1673) is optional**, scope decided later. It
  must still be classified in the inventory.
- The inventory must still classify **all** pages, including KRL and freight.
- The "WAKTU PERJALANAN URUT KERETA API" summary tables (approx. 1829-1864) are a
  **secondary cross-check** for Phase 2 rules V2/V4 (train-number set and travel
  times), not a parsing target. The index pages are the **primary authority** for
  which trains exist and their printed page numbers. Disagreements between index,
  `Relasi` headers and summary tables go to a reconciliation report and are never
  auto-resolved.
- **Train tables are second-precision** (`HH:MM:SS`). Store seconds-of-day; a
  minute-resolution model truncates silently.

Two separate systems:
- **Offline pipeline**: PDF -> clean, validated data. Run once per Gapeka version.
- **Online runtime**: reads only the clean data and computes positions. The PDF and LLMs are **never** used at runtime.

Glossary:
- **Gapeka** = Grafik Perjalanan Kereta Api (official national train timetable).
- **KA** = Kereta Api (train). **No. KA** = train number.
- **Lintas** = rail line/corridor. **Daop** = operating area (regional division).
- **KA langsung** = a train that passes a station without stopping.
- **WIB / WITA / WIT** = Indonesian time zones (UTC+7 / +8 / +9).

## 2. Hard Rules (non-negotiable)

1. **Never guess schedule data.** If a time, station, or train number is unreadable or doubtful, store `null` plus a `needs_review` flag. Never fill values from assumptions.
2. **Never modify the raw layer.** Raw extraction output is append-only. Corrections happen in later layers or via the `overrides` table.
3. **The position estimation function must be pure and deterministic.** Input: time + data. Output: positions. No network, no DB, no system clock inside it.
4. **Store all backend timestamps in UTC.** Gapeka times are stored as station-local time plus time zone (WIB/WITA/WIT). Convert only at display time.
5. **Validation is a gate.** If validation fails, the pipeline stops with a non-zero exit code. Never loosen validation rules just to make tests pass without explicit human approval.
6. **The UI must always show a disclaimer**: "Estimated position based on the Gapeka schedule, not actual position." (Indonesian: "Posisi estimasi berdasarkan jadwal Gapeka, bukan posisi aktual.")
   Additionally, whenever `today < gapeka_versions.effective_from`, the UI must show a config-driven banner, e.g. "Preview Gapeka 2026 (berlaku resmi mulai 1 Desember 2026)". The banner is additive to the disclaimer, never a replacement.
7. **Never commit the original PDF** (58.6 MiB) to git. Keep it in `data/input/` (gitignored) and record its SHA-256 in `gapeka_versions`.
8. **Use an LLM only for problematic pages** in the offline pipeline (complex layouts): temperature 0, strict JSON schema, `null` when unsure. Every LLM output must pass the same validators as parser output.
9. **If the spec is ambiguous or the PDF format does not match assumptions, STOP and ask.** Do not improvise.
10. **Never mix up night-time trips.** Times after midnight on the same trip use `day_offset`, never a new trip.
11. **Never rely on the PDF text-stream order.** Always reconstruct rows and columns from x/y coordinates. (Observed: on KRL pages, `Berangkat` is emitted before `Datang`.)

**Human decisions are versioned (P2).** `data/config/*.yaml` is TRACKED: station overrides,
aliases, segment reviews, bridges, snap pins and cell markers are part of the record. The PDF,
raw words, parsed data, the database, review artefacts and external datasets stay gitignored.
`pipeline/config_tracking.py` hashes every tracked config file; the hash is stored in the DB
build summary and every report, so two builds can be compared honestly.

## 3. Tech Stack (defaults; may be changed with a written reason in `docs/decisions/`)

| Layer | Choice |
|---|---|
| Pipeline language | Python 3.12 |
| PDF extraction | PyMuPDF (`get_text("words")`); cross-checkers: pdfplumber, `pdftotext -layout` |
| Data validation | Pydantic v2 + pytest |
| Storage | SQLite (MVP) -> PostgreSQL + PostGIS (production) |
| Rail geometry | OSM `railway=rail`, networkx / shapely |
| Backend | FastAPI |
| Frontend | MapLibre GL + TypeScript (Vite) |
| Package managers | `uv` (Python), `pnpm` (frontend) |

## 4. Repo Structure

```
.
├── AGENTS.md
├── data/
│   ├── input/            # PDF (gitignored)
│   ├── raw/              # words + coordinates per page (JSON, append-only)
│   ├── parsed/           # parser output per page type
│   ├── validated/        # passed validation
│   └── review/           # manual review queue
├── pipeline/
│   ├── inventory.py      # page classification
│   ├── classify.py       # pure classification heuristics (no I/O)
│   ├── report.py         # inventory.json -> docs/inventory_report.md
│   ├── extract_words.py  # PyMuPDF -> raw
│   ├── parsers/          # one module per page type
│   ├── llm_fallback.py   # problematic pages only
│   ├── validators.py     # validation rules
│   ├── build_db.py       # validated -> database
│   ├── build_geometry.py # OSM -> segments + trip geometry status
│   ├── triple_rail.py    # rail-path neighbour-consistency triples
│   ├── engine_sweep.py   # 24 h sweep + benchmark (R1)
│   ├── engine_replay.py  # self-contained Leaflet replay page (R2)
│   └── phase5_report.py  # -> docs/phase5_report.md
├── engine/
│   ├── model.py          # dataclasses, Policy, SegmentGeom (no I/O)
│   ├── snapshot.py       # the ONLY SQLite reader; verifies hashes
│   ├── profile.py        # trapezoid_v1 motion maths (pure)
│   ├── position.py       # positions_at / trajectory (pure)
│   ├── cli.py            # `python -m engine.cli at|trajectory`
│   └── golden_frames.json # sampled frames for browser-port parity
├── api/                  # FastAPI
├── web/                  # MapLibre frontend
├── tools/review_ui/      # PDF-vs-data review UI
├── tests/
│   ├── unit/
│   └── golden/           # >= 50 manually verified trains
└── docs/decisions/       # short ADRs
```

## 5. Data Contract (reference schema)

Use Pydantic models that mirror this exactly. Any schema change requires an ADR.

- `gapeka_versions(id, name, effective_from, effective_to, pdf_sha256, status[draft|validated|active|retired])`
- `stations(code, name, official_name, name_source, lat, lon, coord_status, coord_source, coord_source_id, coord_match, coord_confidence, coord_retrieved, daop, tz)`
  - `name` is exactly what the PDF prints; `official_name` is the human-verified name from
    `data/config/station_aliases.yaml` (H1) and the UI shows that one. `name_source` is `pdf` or `human`.
  - `coord_status` is `accepted | override | rejected | missing`. Only `accepted` and `override` may
    reach geometry; `rejected` keeps `lat/lon` NULL and its evidence lives in
    `station_coord_candidates`.
- `trains(train_no, name, class, relation)`
- `trips(trip_id, train_no, version_id, operating_days, notes)`
- `stop_times(trip_id, seq, station_code, arrive, depart, arrive_day_offset, depart_day_offset,
  day_offset_source[printed|derived_midnight_dwell], stop_type[stop|pass], needs_review)`
  — **ADR 007.** A stop can arrive at 23:58 and depart at 00:03, so each side carries its own
  day offset. `day_offset` is a deprecated alias for `depart_day_offset`.
- `calendar(trip_id, weekdays, valid_from, valid_to, extra_dates, exclude_dates)`
  — **see ADR 002.** The Gapeka PDF provides a validity **start** date only
  (`Berlaku Mulai Tanggal 01 Desember 2026`, present on all 135 dividers and
  identical everywhere). It states no weekday pattern, no validity end date, and
  no extra/exclude dates. Calendar rows therefore carry a nullable
  `service_pattern` and a `pattern_source` (`gapeka_pdf | assumed | override |
  external`, default `unknown`). The engine takes an explicit `calendar_policy`
  parameter and must never hard-code "runs daily".
- `segments(from_station, to_station, geometry, length_m, geometry_quality[osm|straight_line])`
- `overrides(id, target_table, target_key, patch_json, reason, created_by, created_at)`
- `station_coord_candidates(id, code, source, source_id, lat, lon, status, reason, retrieved_on)` —
  every coordinate ever considered, including rejected ones. Evidence is never deleted.
- `trip_geometry_status(trip_id, status, has_bypassed_waypoints, osm_routed, osm_suspect, straight_line, unmeasured, total_length_m)`
  - `status` is `complete | complete_estimated | has_fallback | has_unmeasured`.
  - `osm_routed_reviewed` (ADR 005) counts as **complete**: a human accepted the route.
  - `complete_estimated` means every non-bypassed hop is `osm_routed` and at least one
    waypoint was bypassed (Q4). `has_bypassed_waypoints` is `1` on those trips.
- `trip_waypoint_estimates(trip_id, seq, station_code, method)` — one row per bypassed
  waypoint (`method = bypass_between_neighbours`). Nothing is dropped silently.
- `data/config/snap_pins.yaml` (human-authored, committed) — **ADR 006.** Pins a station to a
  named OSM way when the nearest edge is the wrong track of a double line. A pin farther than
  `snap_accept_m` is reported as unusable and the normal snap is used.
- `data/config/segment_reviews.yaml` (human-authored, committed) — one decision per
  suspect segment: `accept_route` (quality becomes `osm_routed_reviewed`, counts as
  complete) or `needs_bridge` (stays `osm_suspect`). A review on a non-suspect segment
  is ignored and reported. The pipeline never writes the file. See ADR 005.

Coordinate provenance rules:
- External coordinates come from Wikidata (CC0) then OpenStreetMap (ODbL), never guessed.
- A human decision is recorded in `data/config/station_overrides.yaml` (gitignored, human-authored)
  with source, source_id, corroboration, reason, `decided_by`, `date`. The pipeline never writes it.
- **Neighbour-consistency rule (rail-path version, Q3):** a coordinate is accepted only if it
  is inside Java and snaps to rail within `snap_accept_m`. The triple A-B-C is then tested on the
  **routed rail graph** — `d_rail(A,B) + d_rail(B,C) <= 1.15 * d_rail(A,C)` — together with the
  turn angle at B. A very sharp turn-back (angle `>= 150°`) is classified `junction_turnback`
  and reported as **info**, not failure: a train that reverses at a junction legitimately gives a
  high ratio. The old straight-line test flagged **43** triples (32 distinct stations); the
  rail-path test clears **28** of those stations as false positives (including `BBG`, `CNP`,
  `KH`, `SRI`) and keeps only `AND`, `BD`, `JNG`, `SLO` as failures. See
  `data/review/q3_vs_a3.json` and run `python -m pipeline.triple_rail`.
  A failing entry is reported with its numbers, never applied.
- A coordinate that fails is `rejected`, never silently corrected.
- `stations.coord_provenance` is `external_match | human_override | override_rule_approved`.
  A `decided_by` beginning with `rule:` marks the third; it is reported in its own section,
  never counted as a human choice.
  The rule requires ALL of: exactly one OSM candidate cluster, an exact normalised
  name match, inside the Java bbox, snap within the stated limit, a rail-path triple
  ratio <= 1.15, and neighbour distances consistent with the direct pair.
  If any condition fails the coordinate stays a proposal.
- **Waypoint bypass (Q4):** a row may be skipped only when (a) its `stop_type` is `pass` or
  `unknown_untimed`, (b) its station has no accepted coordinate, (c) both neighbouring rows have
  accepted coordinates, and (d) at most **3** consecutive rows are bypassed. A `stop` row is
  **never** bypassed. The neighbour pair is routed as one segment and the row is recorded in
  `trip_waypoint_estimates`. The bypassed station stays `missing` and flagged; no coordinate is
  ever invented for it.

Domain notes:
- `day_offset` = 0, 1, 2 for times after midnight on the same journey.
- `stop_type = pass` for trains that run through a station without stopping.
- Watch for trains that **change train number at a specific station**, trains that are split or combined, and optional/extra (fakultatif/tambahan) trains.
- One trip may span the effective dates of two Gapeka versions.

Version and calendar policy (ADR 002):
- `gapeka_versions.effective_from` is parsed from the divider line
  (`Berlaku Mulai Tanggal ...` → `2026-12-01`). `effective_to` stays `null`.
- `effective_from` is **metadata, not a gate, during development**: the 2026
  schedule may be shown from today onward even though the previous Gapeka is
  still in force until that date. Enforcement is the config flag
  `enforce_effective_from` (default `false` in development; at production release
  it must be consciously set `true` or deliberately left `false`).
- When `today < effective_from`, the UI shows a config-driven banner, e.g.
  "Preview Gapeka 2026 (berlaku resmi mulai 1 Desember 2026)". The banner is
  additive to the Hard Rule 6 disclaimer, never a replacement.

Observed in sampling, to be verified in Phase 1:
- Train-table columns: `No. | Stasiun dan Perhentian | Kecepatan Maksimum (Km/Jam) | Datang | Berangkat | Keterangan`.
- **`Ls` sits in the `Datang` column**, not in Keterangan. It marks a pass-through (non-stopping) row.
- **`Keterangan` holds footnotes and codes**, e.g. `= ka 46 (ka 46 //)`, `x ka 361 (ka 361 x)`. It is not a control column.
- **Pass-row semantics — TO BE VERIFIED:** a row with `Ls` carries a single time, in `Berangkat`, interpreted as the passing time (`arrive = depart` for the engine). Any counter-example must be reported, not worked around.
- `-` is the document's explicit empty-cell marker. It is expected only at: `Datang` on the first row, `Berangkat` on the last row, and `Kecepatan` on the last row. A `-` anywhere else is a real doubt.
- `0` and `-` are different: some trains print speed `0` at a terminal, others `-`. Never normalise one into the other.
- Footnotes appear inline in the text stream (e.g. `= ka 46 (ka 46 //)`, `// ka 5014 (ka 5014 =)`).
- Header count != train count (many KRL tables use a different header).
- 979 of 1,426 train-table pages carry **two or more** tables; a one-table-per-page parser will drop data.
- Printed page numbers restart at five book boundaries (PDF 58, 670, 834, 1516, 1826).
- **Times are second-precision** (`HH:MM:SS`) on train-table pages. A minute-resolution model truncates silently.
- **Some cells hold an undefined marker token instead of a time** (`Berh` in Datang, `Sb` in Berangkat; see PDF 534 and ADR 003). They are handled neutrally: `time = null`, `time_source = marker`, raw token kept, `stop_type = unknown_untimed`, and the trip carries `has_untimed_markers = true`. The PDF defines neither token, so no meaning is assumed. The UI/engine must label such trips **"coarser estimate"**. The whitelist lives in `data/config/cell_markers.yaml` and is reversible.

## 6. Phases

Each phase has **Tasks**, a **Definition of Done (DoD)**, and a **Human checkpoint**. Do not start the next phase until the DoD is met and the checkpoint is approved.

### Phase 0 — Setup & Inventory
**Tasks**
- Initialize repo, `pyproject.toml`, linting (ruff), pytest, pre-commit, `.gitignore` (including `data/input/`).
- `pipeline/inventory.py`: for every page record page number, orientation/rotation, word count, presence of images, and a type classification (`toc`, `train_table`, `line_table`, `graphic`, `legend`, `other`, `unknown`) using heuristics. Output `data/raw/inventory.json`.
- Short report: page count per type + 20 diverse sample pages.

**DoD**: inventory runs on the whole PDF; every page is classified (including `unknown`); report written to `docs/inventory_report.md`.
**Human checkpoint**: human confirms classification and picks 10-20 sample pages.

### Phase 1 — Raw Extraction & Parsers
**Tasks**
- `extract_words.py`: save words + bbox + rotation per page to `data/raw/page_XXXX.json`. Handle rotated pages.
- Per-page-type parsers in `pipeline/parsers/`: group rows by y (configurable tolerance), columns by x. Start with **one pilot line only**.
- Cross-check: run pdfplumber / `pdftotext -layout` on the same pages; write differences to `data/review/`.
- `llm_fallback.py`: called only for pages that fail parser validation; its output must pass the validators.

**DoD**: pilot line parsed 100% with tests; each parser has real-page fixtures + expected JSON; inter-parser differences documented.
**Human checkpoint**: human verifies the pilot against the PDF (review UI or manually).

### Phase 2 — Validation (quality gate)
Implement in `pipeline/validators.py`, each with positive and negative unit tests:
- V1: times within a trip are monotonically increasing (handling `day_offset`).
- V2: inter-station travel time > 0 and implied speed under a sane limit (configurable).
- V3: every `station_code` exists in the `stations` master.
- V4: number of extracted trains equals the number listed in the PDF index/list.
- V5: consecutive station pairs are connected in the rail topology (after Phase 4; skipped with a flag before that).
- V6: two-parser consistency; differences go to the review queue.
- V7: no trip without stop_times; no duplicate `(train_no, version)`.

Build `tools/review_ui/`: show the PDF page crop next to the extracted data, correct/incorrect buttons, save decisions to `data/review/decisions.json`.

**DoD**: `python -m pipeline.validate` produces a report (pass/fail per rule, list of review items). Exit code != 0 if there are unreviewed violations.
**Human checkpoint**: human reviews a 5% random sample plus all flagged items.

### Phase 3a — MVP assembly (Book 1 + Book 2 only)
**Tasks**
- Schema `db/schema.sql` per section 5, extended for `time_source`, raw cells, `book`, `service_class`, `completeness`, `has_untimed_markers`.
- `pipeline/build_db.py`: idempotent, deterministic, content-hashed. Only validated trains load.
- Stations master: codes from the PDF, coordinates from Wikidata/OSM **only** (never guessed), unmatched listed.
- Cross-book checks and smoke queries; report `docs/phase3a_report.md`.

**DoD**: the MVP slice loads, rebuilds byte-identically, and answers the smoke queries. KRL and freight are explicitly out of scope.

### Phase 3b — KRL and freight (deferred)
KRL (approx. PDF 812-1513) and freight (approx. 1514-1673) wait until the MVP slice
(3a -> geometry -> engine -> map) works end to end. They have their own header
formats (two trains per page, `Berh`/`Sb` markers, `Lintas Pelayanan` only).

### Phase 3c — Scale to the Full Gapeka
**Tasks**
- Run parsers on all sections, batched and idempotent (same result on re-run; cache per page by hash).
- Apply full validation; produce `data/validated/`; `build_db.py` fills the database with `gapeka_versions.status = validated`.
- Apply `overrides` at DB build time (never modify raw/parsed).

**DoD**: entire PDF processed; coverage report in `docs/coverage_report.md`; counts compared with the PDF index.

### Phase 4 — Rail Geometry
**Tasks**
- OSM rail for Java from a hash-pinned **Geofabrik extract** (an Overpass query is not stable enough; see `docs/DATA_SOURCES.md`). Cache under `data/external/` (gitignored) with SHA-256 and retrieval date.
- Routing graph over `railway=rail` ways. **Allowlist, not blocklist:** only real track enters the graph, because a blocklist let `railway=platform` in and fragmented the network. `service=yard` is excluded; **siding, spur and crossover stay in**, because on double track they are the only links between the parallel tracks (excluding them broke 80 of 88 segments).
- Snap each station onto the nearest **edge**, splitting the edge at the projection so routed lengths stay accurate. Distance bands configurable in `data/config/geometry.yaml`.
- Route **every** consecutive stop pair, including `pass` (`Ls`) and untimed rows: the PDF lists every station, so segments stay short and route ambiguity is small.
- Quality tiers: `osm_routed`, `osm_suspect` (detour above the configured ratio), `straight_line` (both ends snapped, no path), `unmeasured` (no accepted coordinate or unsnapped). Nothing is silently routed.
- Validators V5 (connectivity), V12 (detour), V13 (implied speed vs printed maximum — **evidence for Phase 5, not a gate**), V14 (cumulative consistency).
- Human-approved **bridges** (`data/config/geometry_bridges.yaml`) join two OSM nodes that are the same track but were disconnected in the extract (a digitising seam). The pipeline never invents a bridge, and each one is recorded in the report as `human_bridges`. Routing weights stay at the default (no cost tuning).
- `trip_geometry_status` records `complete | complete_estimated | has_fallback | has_unmeasured` per trip; non-complete trips are always listed.
- Snap pins (ADR 006) let a human name the track a station is on; `snap_bands` gains `ok_pinned`.
- Segment reviews (ADR 005) let a human accept a suspect route. `osm_routed_reviewed` counts as complete; `needs_bridge` stays suspect. Evidence page: `data/review/suspect_segments_review.html`. Candidate bridges live in `data/config/geometry_bridges.draft.yaml` and are **never** applied automatically.

**DoD**: segment coverage recorded; every fallback, unmeasured pair and suspect detour listed; stations above the snap-accept threshold listed; review map produced.

### Phase 5 — Position Engine
**Built (see `docs/phase5_report.md`, ADR 004)**

Layout: `engine/model.py` (dataclasses, `Policy`), `engine/snapshot.py` (the only SQLite
reader; verifies the geometry content hash and the `gapeka_versions` row), `engine/profile.py`
(motion maths), `engine/position.py` (`positions_at`, `trajectory`), `engine/cli.py`.
**`profile.py` and `position.py` are pure**: input = snapshot + time + policy; no DB, no network,
no system clock, no randomness.

Time model: every Java station is WIB (`Asia/Jakarta`, asserted on load). Schedule times are
seconds from the start of the **service date**, plus `86400 * day_offset`. For a query instant the
engine scans service dates `date(t_local) - k` for `k in 0..max_day_offset`, so a trip that started
yesterday still appears after midnight.

`positions_at(snapshot, instant, policy)` — `Policy` is explicit and immutable:
`calendar_policy = "regular_daily_assumed"`, `show_fakultatif = False`,
`enforce_effective_from = False`, `geometry_policy in {complete_and_estimated (default),
complete_only, allow_fallback}`, `accel_time_s = 60`, `origin_lead_s = 0`,
`terminal_linger_s = 0`. Trips with an unknown `service_class` are treated like fakultatif.

Motion (`motion_model = "trapezoid_v1"`, ADR 004): between consecutive **timed** waypoints, a
trapezoidal profile. An end gets an acceleration/deceleration phase only if that row is a `stop`;
`pass` rows get none. `a_s = min(accel_time_s, D/3)`, `v = L / (D - a_s/2 - a_e/2)`, and the
profile reaches exactly `S_j` at `T_j`. This is an **assumption**, not Gapeka data.

Rules per active trip:
1. Determine the operating day, including trips that started yesterday (`day_offset`).
2. `arrive <= t <= depart` at a station -> status `at_station`.
3. `depart_A < t < arrive_B` -> status `running`; the position is the point on the trip polyline at
   the distance given by the motion profile.
4. `pass` rows (non-stopping trains): no dwell, interpolate continuously.
5. Before the first departure / after the last arrival -> not returned.
6. Untimed rows inside a leg only mark distance; they never create a pause.

Every output carries `estimated = true`, `motion_model`, and the flags `coarse`
(`has_untimed_markers`), `has_bypassed_waypoints`, `has_straight_line_segment`.

Geometry policy: `complete` and `complete_estimated` are shown by default; `allow_fallback` also
draws `has_fallback` trips with flags; **`has_unmeasured` is never shown, under any policy**.

**DoD**: unit tests cover midnight crossing, non-stopping trains, dwell < 1 min, fakultatif
hidden/shown, `enforce_effective_from`, `has_unmeasured` never shown, `straight_line` flagged,
bypassed waypoints; property tests confirm the distance is monotonic, the position lies on the
polyline, and speed is bounded; a 250-frame regression set is exported. The golden test of
>= 50 **manually verified** trains is still open — the 6 pilot trains are parsed but only their
pilot rows are human-verified.

**Browser-port parity requirement (Phase 6):** if positions are computed in the browser, the
TypeScript port must reproduce `trapezoid_v1` and the time model exactly, and its output must match
`engine/golden_frames.json` (250 frames: `trip_id`, `t_s`, `time`, `lat`, `lon`, `s_m`, `status`)
within 1 m. Those frames are **not** human-verified; they are a parity fixture, not a correctness
claim. Any disagreement means the port is wrong, not the fixture.

### Phase 6 — API & Frontend
**Backend (FastAPI)**
- `GET /positions?t=&bbox=` · `GET /trains/{no}` · `GET /stations/{code}/board` · `GET /schedule/active` (static schedule data for clients).
- Load the active schedule into memory; short-lived result cache; the active Gapeka version is chosen by date, never by overwriting old data.

**Frontend (MapLibre)**
- Smoothly moving train markers, detail panel (schedule, next station), station board, search by train number/station, "replay" mode (pick any time), OSM attribution, clear disclaimer.
- **Pre-release preview banner** (Hard Rule 6, ADR 002): when `today < effective_from`, show a config-driven banner such as "Preview Gapeka 2026 (berlaku resmi mulai 1 Desember 2026)". It sits alongside the disclaimer, not instead of it.
- Scaling option: compute positions in the browser from static schedule data (port the logic of `engine/position.py` with parity tests against the Python version).

Every trip with `has_untimed_markers = true` must be labelled "coarser estimate" wherever its position is shown, because its position spans a longer untimed gap.

**DoD**: e2e smoke test (Playwright) passes; basic performance check done; 500+ active trains render smoothly on a mid-range device.

### Phase 7 — Operations & Release
- Release flow: extract -> validate -> review -> staging -> swap to production, with one-command rollback.
- Monitoring: log trains without schedules, validation failures, API latency.
- Docs: `docs/RUNBOOK.md` (how to process a new/revised Gapeka), `docs/DATA_SCHEMA.md`.
- CI: lint + unit + golden tests + sample validation on every PR.
- **Release-date checklist (ADR 002):** the official effective date is 2026-12-01; before release decide `enforce_effective_from` and the pre-release UI behaviour (preview banner). Record the decision in `docs/decisions/`.

**DoD**: the next Gapeka version (or a revision) can be processed by following the runbook without changing core code.

## 7. Standard Commands (create and maintain in a Makefile)

```
make setup        # install dependencies
make inventory    # classify PDF pages
make extract      # PDF -> raw
make parse        # raw -> parsed
make validate     # run all validators; fail on any violation
make build-db     # validated -> database
make geometry     # OSM -> segments
make triple       # rail-path neighbour-consistency triples (Q3) + q3_vs_a3.json
make engine-sweep # 24 h sweep + benchmark (R1)
make engine-replay# self-contained replay page (R2, 30 h window)
make suspects     # suspect-segment review page + draft bridges
make coverage     # coverage blockers (T3)
make h5h6         # H5/H6 gate record
make day-offsets  # midnight-straddling rows report (Q3)
make bridge-probe # what each draft bridge would change (P4)
make snap-experiment # routing-aware snapping, experiment only (Q1b)
make reports      # regenerate the generated reports
make test         # unit + golden
make serve        # API + web dev
```

## 8. Working Conventions for the Agent

- **Every number quoted in a chat summary must be copied from a generated artefact** (`docs/*.md` or
  `data/review/*.json`), never recomputed by hand. Hand arithmetic has already produced wrong figures
  that contradicted the generated reports.

- One phase per session; small commits with clear messages (`feat(parser): ...`).
- Write tests **before or together with** parsers and validators. Fixtures use real pages (crop small pages; never the whole PDF).
- When a parser bug is found: first add a fixture that reproduces it, then fix it.
- Any architecture decision that deviates from this document -> a short file at `docs/decisions/NNN-title.md`.
- At the end of each phase, write a summary: what was completed, coverage metrics, open issues, and questions for the human.
- Do not add heavy dependencies without justification; record the reason in an ADR.
- Do not silently skip or drop pages, trains, or rows. Anything not processed must appear in a report.

## 9. Risks to Keep Watching

| Risk | Handling |
|---|---|
| Table/column misreads | Layered validation, two parsers, manual review |
| Incomplete OSM rails | Straight-line fallback + flag + report |
| Gapeka format changes | Modular per-page-type parsers, fixtures, tests |
| Real trains running late | Label as "schedule estimate"; leave a hook for an official real-time data source if one becomes available |
| Data/map usage rights | Confirm legal rights before going public; OSM attribution required |
| Load during long holidays | Compute positions on the client; API serves only static data |

## 10. Example Session Opening Prompt

> Read `AGENTS.md`. Do **Phase 1** for one pilot line. Follow the Hard Rules. Write tests together with the code. If the PDF page format does not match the assumptions, stop and report your findings instead of guessing. At the end, give a summary as described in section 8.
