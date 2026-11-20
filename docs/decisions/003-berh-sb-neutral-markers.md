# ADR 003 — Berh / Sb are handled neutrally; their meaning is undefined

- Status: accepted (human-approved default, reversible)
- Date: 2026-11-20
- Supersedes: nothing. Extends ADR 002.
- Context: Phase 2b — 68 trains quarantined on two cell tokens

## Context

Some commuter tables print `Berh` in the *Datang* column and `Sb` in the
*Berangkat* column instead of clock times, e.g. on PDF page 534. The human
confirmed by inspection that the PDF really prints them.

A full-document search found **no definition of either token**: no glossary, no
legend, no `Berh = ...` line, nothing in the front matter or the Lampiran IV
notes. `FAKULTATIF` is defined as a *classification*, but it does not explain
these cell codes.

Quarantining 68 trains indefinitely would block the MVP. Inventing a meaning
(whether the train stops, passes, or is cancelled) would violate Hard Rule 1.

## Decision

1. **A whitelist lives in `data/config/cell_markers.yaml`.** Only `Berh` and `Sb`
   are enabled. `B.hu` / `B.hi` are listed as *observed but not enabled*.
2. **A whitelisted token is handled neutrally:**
   - `time = null` — no time is invented;
   - `time_source = "marker"`;
   - the raw token is preserved verbatim;
   - `stop_type = "unknown_untimed"` — we never claim the row is a stop or a pass;
   - `estimated = true` on the affected cells.
3. **V10 still applies.** The first and last row of a trip must be timed, and
   every untimed row must lie between two timed rows. Per train, the number of
   untimed rows and the longest consecutive untimed run are reported.
4. **Marker trains are loadable**, flagged `has_untimed_markers = true`. The UI
   and engine must label their output "coarser estimate" — the position is
   interpolated across a longer, less certain span.
5. **This is a human-approved default, and it is reversible.** If the tokens are
   ever defined (a KAI document, a later Gapeka legend), the whitelist gains a
   `meaning` and the parser can be tightened without touching stored data.

## Consequences

- 68 previously quarantined trains become loadable (Book 1: 8, Book 2: 60).
- Those trains carry honestly weaker position estimates; the flag makes that
  visible rather than silent.
- A reviewer can always see the original token, because it is never discarded.
- If `Berh`/`Sb` turn out to mean "cancelled on this day", the engine's "coarser
  estimate" label would be wrong for those rows. That risk is recorded here.

## Alternatives considered

- **Keep them quarantined.** Rejected: blocks the MVP on an undefined token.
- **Treat them as stops with a NULL time.** Rejected: it asserts a stop, which
  the document does not state.
- **Treat them as passes.** Rejected for the same reason, in the other direction.
- **Drop those rows.** Rejected: silently loses stations from a trip, breaking
  V11 continuity and the segment graph.
