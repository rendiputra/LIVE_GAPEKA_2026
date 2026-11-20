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
