"""One definition of "which segments does a trip use" (P3).

Two reports disagreed about SB-SBI: one counted 0 trips, the other 25. The cause
was not a bug in either number, but two different definitions:

- the parsed trip sequence has ``SBI -> STM -> SB`` (STM is a row in the PDF), so
  SB-SBI is never adjacent;
- the database sequence applies the Q4 bypass, so STM disappears and ``SBI -> SB``
  becomes consecutive.

Geometry routes the BYPASSED sequence, so that is the definition every report must
use. This module is the single source of it.

Usage:
    python -m pipeline.trip_pairs
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

DEFAULT_DB = Path("data/gapeka.db")


def trip_pairs(connection: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """Consecutive station pairs per trip, honouring the Q4 bypass."""
    bypassed: dict[str, set[int]] = {}
    for trip_id, seq in connection.execute("SELECT trip_id, seq FROM trip_waypoint_estimates"):
        bypassed.setdefault(trip_id, set()).add(seq)

    out: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    previous: str | None = None
    sequence: list[tuple[str, str]] = []

    for trip_id, seq, code in connection.execute(
        "SELECT trip_id, seq, station_code FROM stop_times ORDER BY trip_id, seq"
    ):
        if trip_id != current:
            if current is not None:
                out[current] = sequence
            current, previous, sequence = trip_id, None, []
        if seq in bypassed.get(trip_id, set()):
            continue
        if previous is not None and previous != code:
            sequence.append((previous, code))
        previous = code
    if current is not None:
        out[current] = sequence
    return out


def segment_usage(pairs: dict[str, list[tuple[str, str]]]) -> Counter:
    """How many trips use each undirected segment."""
    counter: Counter = Counter()
    for sequence in pairs.values():
        seen = set()
        for a, b in sequence:
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            counter[key] += 1
    return counter


def load(db_path: Path = DEFAULT_DB) -> tuple[dict[str, list[tuple[str, str]]], Counter]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        pairs = trip_pairs(connection)
    finally:
        connection.close()
    return pairs, segment_usage(pairs)


def main() -> int:
    pairs, usage = load()
    print(f"{len(pairs)} trips, {len(usage)} segments used")
    for key, count in usage.most_common(5):
        print(f"  {key[0]}-{key[1]}: {count} trips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
