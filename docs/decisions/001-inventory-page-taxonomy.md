# ADR 001 — Inventory page taxonomy and section model

- Status: accepted (Phase 0)
- Date: 2026-11-19
- Context: Phase 0 inventory of `GAPEKA_2026.pdf`

## Context

AGENTS.md section 6 defines seven page types (`toc`, `train_table`, `line_table`,
`graphic`, `legend`, `other`, `unknown`) and asks the inventory to classify every
page. Sampling the real document showed that seven labels are not enough to
describe what is actually on the page:

- 135 pages are section dividers (`DAFTAR WAKTU ... ISI:`), not tables.
- 62 pages are multi-train summary tables, in three different shapes.
- 209 pages are graphics: stringline charts, rolling-stock diagrams, seat maps,
  capacity charts, and inter-station distance tables.
- The document is organised into books (Lampiran I-IV plus a freight book), each
  with its own page numbering.

A single `type` field cannot carry both "what shape is this page" and "which part
of the document is it in".

## Decision

1. **The seven-value `type` enum is unchanged.** No new type values.
2. **Two fields are added to each inventory record:**
   - `subtype` — a free-form string (`section_divider`, `summary_by_train`,
     `summary_by_line`, `stringline_chart`, `rolling_stock`, `seat_map`,
     `capacity_chart`, `distance_table`, `cover_decree`, `image_only`,
     `near_empty`, `title_page`, `intercity_train_table`, `krl_train_table`,
     `freight_train_table`, `toc_intercity`, `toc_krl`, `toc_freight`, `toc`,
     `legend`, `unknown`).
   - `section` — one of `cover`, `stringline`, `intercity`, `krl`, `freight`,
     `rolling_stock`, `summary`, `annex`.
3. **Section boundaries are derived from content markers, never from page
   numbers.** The markers live in `pipeline/classify.py::section_transition`:
   annex covers (`LAMPIRAN I..IV` + `KEPUTUSAN DIREKTUR JENDERAL`, short page),
   the KRL index header, the freight index header, and the capacity-annex title.
   The page ranges in the report are the *result* of that walk, used only as a
   cross-check.
4. **A `freight` section was added** beyond the list agreed for Phase 0. PDF
   pages 1514-1673 are a separate KA barang book with its own index and page
   numbering. Labelling them `krl` or `intercity` would have been wrong, and
   silently mislabelling is worse than extending an inventory-only enum.
5. **`confidence` is defined as:**
   - `high` — matched a distinctive content marker (rules 1-5);
   - `medium` — matched a structural or statistical heuristic (rules 6-9);
   - `low` — no rule matched (rule 10, `unknown`).
   `high` means the marker is unambiguous, **not** that the page was verified.
6. **`inventory.json` is a derived index, not the raw layer.** It is regenerated
   on every run and is byte-identical for the same input: no timestamps, no
   randomness, no dict-order dependence. Hard Rule 2 (append-only) applies to the
   Phase 1 word layer (`data/raw/page_XXXX.json`), not to this index.
7. **Rule order is part of the contract.** Rules 4 (divider) and 5 (annex cover)
   run before rules 6 (summary) and 7 (graphic) because divider pages quote
   "Lintas Pelayanan" and "rangkaian" in their own notes. Reordering them
   misclassifies 135 pages.

## Consequences

- The inventory carries more information than the seven-type contract requires,
  without changing the contract.
- Section boundaries are marker-based, so a Gapeka format change can silently
  move a boundary. The report lists the resulting ranges so a human can spot it.
- `freight` is an inventory-only value. If freight ever enters the data contract,
  it needs its own ADR.
- The classifier is pure and unit-tested without a PDF; the extractor is tested
  against a synthetic PDF built at test time, so no Gapeka content is committed.

## Alternatives considered

- **Add new `type` values** (`divider`, `chart`, `freight_table`). Rejected: it
  changes the contract AGENTS.md fixes, and the seven types still describe the
  page shape correctly.
- **Hardcode page ranges per section.** Rejected: it breaks on the next Gapeka
  revision and hides format changes instead of surfacing them.
- **Infer section from the printed page number.** Rejected: the offset restarts
  at five different book boundaries, and the stringline annex uses roman-prefixed
  numbers that the extractor cannot read reliably.
