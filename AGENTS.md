# AGENTS.md — Gapeka-Based Train Position Estimator

> Place this file at the repo root. Works with Claude Code (copy or symlink to `CLAUDE.md`), Codex, Cursor, etc.
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
- The inventory must still classify **all** pages, including KRL and freight.
- The "WAKTU PERJALANAN URUT KERETA API" summary tables (approx. 1829-1864) are a
  **cross-validation source** for Phase 2 rules V2/V4, not a parsing target.

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
7. **Never commit the original PDF** (58.6 MiB) to git. Keep it in `data/input/` (gitignored) and record its SHA-256 in `gapeka_versions`.
8. **Use an LLM only for problematic pages** in the offline pipeline (complex layouts): temperature 0, strict JSON schema, `null` when unsure. Every LLM output must pass the same validators as parser output.
9. **If the spec is ambiguous or the PDF format does not match assumptions, STOP and ask.** Do not improvise.
10. **Never mix up night-time trips.** Times after midnight on the same trip use `day_offset`, never a new trip.
11. **Never rely on the PDF text-stream order.** Always reconstruct rows and columns from x/y coordinates. (Observed: on KRL pages, `Berangkat` is emitted before `Datang`.)

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
│   └── geometry.py       # OSM -> segment polylines
├── engine/
│   └── position.py       # pure position estimation function
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
- `stations(code, name, lat, lon, daop, tz)`
- `trains(train_no, name, class, relation)`
- `trips(trip_id, train_no, version_id, operating_days, notes)`
- `stop_times(trip_id, seq, station_code, arrive, depart, day_offset, stop_type[stop|pass], needs_review)`
- `calendar(trip_id, weekdays, valid_from, valid_to, extra_dates, exclude_dates)`
- `segments(from_station, to_station, geometry, length_m, geometry_quality[osm|straight_line])`
- `overrides(id, target_table, target_key, patch_json, reason, created_by, created_at)`

Domain notes:
- `day_offset` = 0, 1, 2 for times after midnight on the same journey.
- `stop_type = pass` for trains that run through a station without stopping.
- Watch for trains that **change train number at a specific station**, trains that are split or combined, and optional/extra (fakultatif/tambahan) trains.
- One trip may span the effective dates of two Gapeka versions.

Observed in sampling, to be verified in Phase 1:
- Train-table columns: `No. | Stasiun dan Perhentian | Kecepatan Maksimum (Km/Jam) | Datang | Berangkat | Keterangan`.
- `Ls` in Keterangan = pass-through (non-stopping); `-` = empty cell.
- Footnotes appear inline in the text stream (e.g. `= ka 46 (ka 46 //)`, `// ka 5014 (ka 5014 =)`).
- Header count != train count (many KRL tables use a different header).
- 979 of 1,426 train-table pages carry **two or more** tables; a one-table-per-page parser will drop data.
- Printed page numbers restart at five book boundaries (PDF 58, 670, 834, 1516, 1826).

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

### Phase 3 — Scale to the Full Gapeka
**Tasks**
- Run parsers on all lines, batched and idempotent (same result on re-run; cache per page by hash).
- Apply full validation; produce `data/validated/`; `build_db.py` fills the database with `gapeka_versions.status = validated`.
- Apply `overrides` at DB build time (never modify raw/parsed).

**DoD**: entire PDF processed; coverage report (pages parsed, trains parsed, remaining review items) in `docs/coverage_report.md`; counts compared with the PDF index.

### Phase 4 — Rail Geometry
**Tasks**
- Download/extract OSM `railway=rail` for the coverage area; build a graph; snap stations to the nearest node (configurable distance threshold).
- For each consecutive stop pair in `stop_times`, compute the shortest path -> polyline + cumulative distance -> `segments`.
- On failure: straight-line fallback, set `geometry_quality = 'straight_line'`, record in the report.
- Enable validation V5.

**DoD**: OSM segment coverage meets the target (agreed with the human); list of fallback segments and problematic stations produced; stations with off-target coordinates flagged.

### Phase 5 — Position Engine
**Tasks**: `engine/position.py` with a pure function, e.g. `positions_at(t_utc, schedule) -> list[TrainPosition]`.

Logic per active trip:
1. Determine the operating day, including trips that started yesterday and are still running (`day_offset`).
2. `arrive <= t <= depart` at a station -> status `at_station`.
3. `depart_A < t < arrive_B` -> status `running`; `progress = (t - depart_A) / (arrive_B - depart_A)`; apply an ease-in-out curve; position = point on the polyline at `progress * length`.
4. `pass` stations (non-stopping trains): do not pause; interpolate continuously.
5. Before the first time / after the last time -> not returned.

**DoD**: unit tests cover midnight crossing, non-stopping trains, very short dwell (<1 min), Gapeka version switchover, non-operating days, `straight_line` fallback; golden test of >= 50 manually verified trains passes; property tests: progress always in [0,1] and position always lies on the polyline.

### Phase 6 — API & Frontend
**Backend (FastAPI)**
- `GET /positions?t=&bbox=` · `GET /trains/{no}` · `GET /stations/{code}/board` · `GET /schedule/active` (static schedule data for clients).
- Load the active schedule into memory; short-lived result cache; the active Gapeka version is chosen by date, never by overwriting old data.

**Frontend (MapLibre)**
- Smoothly moving train markers, detail panel (schedule, next station), station board, search by train number/station, "replay" mode (pick any time), OSM attribution, clear disclaimer.
- Scaling option: compute positions in the browser from static schedule data (port the logic of `engine/position.py` with parity tests against the Python version).

**DoD**: e2e smoke test (Playwright) passes; basic performance check done; 500+ active trains render smoothly on a mid-range device.

### Phase 7 — Operations & Release
- Release flow: extract -> validate -> review -> staging -> swap to production, with one-command rollback.
- Monitoring: log trains without schedules, validation failures, API latency.
- Docs: `docs/RUNBOOK.md` (how to process a new/revised Gapeka), `docs/DATA_SCHEMA.md`.
- CI: lint + unit + golden tests + sample validation on every PR.

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
make test         # unit + golden
make serve        # API + web dev
```

## 8. Working Conventions for the Agent

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
