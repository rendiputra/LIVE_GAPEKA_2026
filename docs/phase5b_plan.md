# Phase 5b plan

## Root causes / decisions

- **F-a root cause**: `pipeline/engine_replay.py` iterates `range(0, 86400, STEP_S)`
  (max elapsed 86370) and calls the private `_position_for` with a single
  service-date-relative elapsed. The engine is correct: `positions_at` returns
  KA 260F at both 2026-12-01 00:05 (service date 11-30) and 2026-12-02 00:05
  (service date 12-01). Fix = generate via the public `positions_at` over a
  30 h window. Regression test required.

## Order (coordinates first, then everything downstream)

1. H5 TLM override + safety gate (snap <= 300 m, rail-path triple CIT-TLM-CKR)
2. H6 SRI: OSM search, alias-aware; apply only if ALL 5 conditions hold
3. T2 segment-review mechanism (`segment_reviews.yaml` loader + tests) and
   `geometry_bridges.draft.yaml` (NOT applied)
4. T1 rebuild geometry + DB; before/after from generated files
5. T3 coverage blockers
6. T4 replay: positions_at, 30 h window, routes, stations, reproduction check
7. T5 R1 sweep incl. previous-day tails
8. T6 docs: phase5b report section, AGENTS.md diff, ADR 005

## Constraints

- Never apply a bridge or a segment review myself.
- Never invent a coordinate.
- Every quoted number comes from a generated file.
