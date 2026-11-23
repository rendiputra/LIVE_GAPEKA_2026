# ADR 002 — Gapeka provides a validity start date only; operating days are unknown

- Status: accepted
- Date: 2026-11-20
- Context: Phase 1 calendar investigation

## Context

The Phase 5 engine has to know which days a train runs. AGENTS.md section 5
therefore lists a `calendar` table with `weekdays`, `valid_from`, `valid_to`,
`extra_dates`, and `exclude_dates`.

A full-document investigation (Phase 1, step 2b) found that **the PDF does not
contain that information**.

What the dividers do carry, on every one of them, is a single line:

> `Berlaku Mulai Tanggal 01 Desember 2026`

What they do **not** carry:

- any weekday pattern (`Senin`, `Selasa`, …, `harian`, `setiap hari`) — zero hits
  in a per-train context across all 1,887 pages;
- a validity **end** date;
- an extra/optional-date list;
- a per-train composition or calendar annotation.

`FAKULTATIF` exists, but only as a **classification column value** in the
Lampiran IV summary tables (`REGULER : n / FAKULTATIF : m`). It classifies a
train; it does not say which dates it runs.

## Decision

1. **`calendar` rows carry a nullable `service_pattern` and a `pattern_source`**
   with values `gapeka_pdf | assumed | override | external`, defaulting to
   `unknown`. The PDF populates neither, so every row starts `unknown`.
2. **The engine takes an explicit `calendar_policy` parameter.** It must never
   hard-code "runs daily". A missing policy is a programming error, not a
   default.
3. **`gapeka_versions.effective_from` is parsed from the dividers**
   (`Berlaku Mulai Tanggal ...` → `2026-12-01`). `effective_to` stays `null`
   because the PDF does not state it.
4. **`effective_from` is metadata, not a gate, during development.**
   The previous Gapeka is still in force until 2026-12-01, but the 2026 schedule
   may be displayed from today onward while the product is being built.
   Enforcement is a config flag, `enforce_effective_from`:
   - default `false` in development;
   - at production release it must be **consciously** set to `true` or left
     `false`, and that decision recorded.
5. **Until the effective date the UI shows a banner** whenever
   `today < effective_from`, e.g. *"Preview Gapeka 2026 (berlaku resmi mulai
   1 Desember 2026)"*. The banner is config-driven, not hard-coded, and it is
   additive to — never a replacement for — the Hard Rule 6 disclaimer.
6. **The `F` suffix is evidenced, not interpreted.** See
   `docs/phase2a_report.md`: every train number carrying an `F` in the Lampiran IV
   summary tables is classified `FAKULTATIF`, and vice versa, with zero
   exceptions across 181 numbers. That is a correlation in the document, not a
   semantic definition; the PDF never defines the suffix.

## Consequences

- The `calendar` table is created but stays `unknown` until an override or an
  external source fills it. The engine cannot claim a train runs on a given day.
- Position output is therefore "this train's scheduled pattern, if it operates
  that day". Any UI that implies guaranteed daily operation would be wrong.
- A Gapeka revision that adds weekday information would populate
  `pattern_source = gapeka_pdf` with no schema change.
- Release must revisit `enforce_effective_from` and the pre-release banner.

## Alternatives considered

- **Assume daily operation.** Rejected: it invents data, violating Hard Rule 1.
- **Infer weekdays from the number of trains per day.** Rejected: there is no
  evidence per train, and it would silently fill a table with guesses.
- **Block all output until 2026-12-01.** Rejected by the human: development needs
  the schedule visible now, with a banner instead.

---

## Amendment 2026-11-23 — pre-release banner removed from `frontend/` (human decision)

- Status: accepted (supersedes decision 5 **for `frontend/` only**)
- Applies to: `frontend/` (branch `feat/frontend-revamp`). `web/` keeps decision 5 unchanged.

### Context

Decision 5 above requires a preview banner whenever `today < effective_from`, and
Hard Rule 6 made it additive to — never a replacement for — the disclaimer. The
Phase 6 baseline in `web/` implements exactly that: a top banner plus a
footer disclaimer bar on the main canvas.

The human reviewed that implementation and rejected the visual result: two
always-on text blocks (banner + footer) dominate a map that is mostly canvas, and
the disclaimer is repeated where it is least read.

### Decision

For `frontend/` only:

1. **The top "Preview Gapeka 2026" banner is removed completely.** The
   `preview_banner` string is not exported to the frontend at all
   (`pipeline/export_web.py --variant frontend` drops the key), so the UI cannot
   render it by accident. Removing it from the payload — rather than shipping it
   and ignoring it — is what makes this decision enforceable rather than a
   convention.
2. **The main-canvas footer disclaimer bar is removed.** The canvas carries no
   persistent legal text.
3. **A clean micro-indicator replaces both**, in the existing top-right status
   pill: `Live (Estimasi) · HH:MM WIB`. It states, permanently and compactly, that
   positions are estimates, and it is visible at all times — so the *fact* of the
   disclaimer is never absent from the screen.
4. **The full disclaimer moves into the "Tentang" (About) modal.** It carries:
   - the Hard Rule 6 sentence *"Posisi estimasi berdasarkan jadwal Gapeka 2026,
     bukan posisi aktual. Diasumsikan tepat waktu dan beroperasi setiap hari."*;
   - the effective date (1 Desember 2026) and the data content hash;
   - OSM/ODbL, OpenFreeMap and OpenRailwayMap attribution (ADR 010);
   - the non-affiliation notice (not affiliated with PT KAI / Kemenhub).

### Why this does not weaken Hard Rule 6

Hard Rule 6 exists so a user can never mistake an estimate for a live position.
The `Live (Estimasi)` pill is on screen continuously and states the estimate
status in the primary reading position; the full legal text is one click away in
a stable, discoverable location. What is removed is *duplication and visual
weight*, not disclosure. `web/` continues to demonstrate the additive form, so
the two can be compared honestly.

### Consequences

- `AGENTS.md` Hard Rule 6 and the Phase 6 DoD are amended to scope the banner to
  `web/` and to describe the `frontend/` form. See ADR 010 for the basemap.
- `enforce_effective_from` is unchanged (still `false` in development); this
  amendment is about *presentation*, not about whether the schedule may be shown.
- The release gate "disclaimer and preview banner visible" (AGENTS.md §7, item 6)
  must be re-read as "disclaimer reachable and estimate status visible"; the
  Playwright smoke test asserts the pill text and the About modal contents
  instead of a banner that no longer exists.
- If a future Gapeka revision needs a real "preview" warning (e.g. a schedule
  that is not yet in force at all), it is a new decision, not a revert of this
  one.

