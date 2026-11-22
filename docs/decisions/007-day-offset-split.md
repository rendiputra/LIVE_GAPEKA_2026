# ADR 007 — Separate arrive/depart day offsets

- Status: accepted (Phase 5c)
- Date: 2026-11-22
- Context: a stop that arrives before midnight and departs after it

## Context

A Gapeka row prints `Datang` and `Berangkat` separately, so a train can arrive at
23:58 and depart at 00:03. The schema stored one `day_offset` per row, which cannot
represent both. Whichever value you pick, one side is a day wrong.

Measured effect before the fix: the arrival was pushed 24 hours late, so the engine
made the train crawl for a day. The replay's reproduction check reported 89
mismatches, **all** traceable to this.

## Decision

`stop_times` gains two explicit columns:

- `arrive_day_offset`
- `depart_day_offset`

and `day_offset_source` (`printed | derived_midnight_dwell`). The old `day_offset`
is kept as a **deprecated alias for the departure side**; new code reads the two
explicit columns.

The derivation is one rule, applied only when the clock goes backwards on the same
row:

```
if arrive_seconds > depart_seconds:  arrive_day_offset = day_offset - 1
else:                                arrive_day_offset = day_offset
```

Nothing else is inferred. A row where the two offsets differ is marked
`derived_midnight_dwell`, so the derivation is visible per row.

V1 now compares **absolute** times built from these offsets. The old "+24 h
rollover allowance" is gone: it was hiding exactly this defect.

## Consequences

- 12 rows are derived; all are `stop` rows and none has a dwell over 60 minutes.
- The replay reproduction check dropped from 89 mismatches to **0** in both the
  default and the fakultatif-visible policies.
- The engine's `Waypoint.arrive_abs` / `depart_abs` use their own offsets.
- A future Gapeka that prints a genuine 25-hour dwell would be flagged by the
  long-dwell report rather than silently accepted.

## Alternatives considered

- **Pick the larger offset for the whole row.** Rejected: it makes the arrival a
  day late, which is the bug being fixed.
- **Treat the arrival as day 0 always.** Rejected: wrong for a stop that arrives
  just after midnight.
- **Split the row into two rows.** Rejected: the PDF prints one row and the review
  UI maps one row to one row.
