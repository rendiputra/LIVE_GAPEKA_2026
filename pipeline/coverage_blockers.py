"""T3: why are trips not shown, and which single fix would unblock most of them?

Default policy shows `reguler` trips whose geometry status is `complete` or
`complete_estimated`. Every other trip is hidden. This module reports:

- hidden trips per reason, per book;
- for `has_unmeasured` / `has_fallback` trips, the blockers ranked by a GREEDY
  marginal gain (fix this one thing, how many NEW trips become showable);
- the services (train numbers/names) that are never shown.

Outputs ``data/review/coverage_blockers.json``. Nothing is changed.

Usage:
    python -m pipeline.coverage_blockers
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = Path("data/gapeka.db")
OUT = Path("data/review/coverage_blockers.json")

TOP_N = 20

# Segment qualities that block a trip under the default policy.
BLOCKING_QUALITIES = ("unmeasured", "straight_line", "osm_suspect")


def load_rows(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        "SELECT t.trip_id, t.train_no, t.book, t.service_class, g.status,"
        " tr.name, t.relation, t.has_untimed_markers, g.has_bypassed_waypoints"
        " FROM trips t"
        " JOIN trip_geometry_status g ON g.trip_id = t.trip_id"
        " LEFT JOIN trains tr ON tr.train_no = t.train_no"
        " ORDER BY t.book, t.train_no"
    ).fetchall()
    return [
        {
            "trip_id": row[0],
            "train_no": row[1],
            "book": row[2],
            "service_class": row[3],
            "status": row[4],
            "name": row[5],
            "relation": row[6],
            "coarse": bool(row[7]),
            "bypassed": bool(row[8]),
        }
        for row in rows
    ]


def trip_segments(connection: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """Consecutive station pairs per trip, honouring the bypassed rows."""
    bypassed: dict[str, set[int]] = defaultdict(set)
    for trip_id, seq in connection.execute("SELECT trip_id, seq FROM trip_waypoint_estimates"):
        bypassed[trip_id].add(seq)

    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    current = None
    previous = None
    for trip_id, seq, code in connection.execute(
        "SELECT trip_id, seq, station_code FROM stop_times ORDER BY trip_id, seq"
    ):
        if trip_id != current:
            current, previous = trip_id, None
        if seq in bypassed.get(trip_id, set()):
            continue
        if previous is not None and previous != code:
            out[trip_id].append(tuple(sorted((previous, code))))
        previous = code
    return out


def segment_quality(connection: sqlite3.Connection) -> dict[tuple[str, str], str]:
    return {
        tuple(sorted((row[0], row[1]))): row[2]
        for row in connection.execute(
            "SELECT from_station, to_station, geometry_quality FROM segments"
        )
    }


def station_status(connection: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in connection.execute("SELECT code, coord_status FROM stations")}


def is_shown(row: dict) -> bool:
    """The default policy, expressed once."""
    if row["status"] not in ("complete", "complete_estimated"):
        return False
    return row["service_class"] == "reguler"


def reason_of(row: dict) -> str | None:
    if is_shown(row):
        return None
    if row["status"] == "has_unmeasured":
        return "unmeasured"
    if row["status"] == "has_fallback":
        return "fallback"
    if row["service_class"] == "fakultatif":
        return "fakultatif"
    if row["service_class"] != "reguler":
        return "unknown_class"
    return "other"


def greedy(blocked: dict[str, set[str]]) -> list[dict]:
    """Rank blockers by marginal gain, recomputing after each chosen fix.

    A trip becomes showable only when ALL of its blockers are fixed. One step
    therefore:

    1. counts, per candidate blocker, the remaining trips whose ONLY remaining
       blocker is that one — those are the trips this fix truly unblocks now;
    2. if some candidate unblocks something, take the best one;
       otherwise take the blocker that touches the most remaining trips (it makes
       progress but unblocks nothing on its own) and say so;
    3. remove the unblocked trips and drop the chosen blocker from the rest.
    """
    remaining = {trip: set(items) for trip, items in blocked.items() if items}
    ranking: list[dict] = []

    while remaining and len(ranking) < TOP_N:
        sole: Counter[str] = Counter()
        touched: Counter[str] = Counter()
        for items in remaining.values():
            for item in items:
                touched[item] += 1
            if len(items) == 1:
                sole[next(iter(items))] += 1

        if sole:
            best, gain = sole.most_common(1)[0]
            mode = "unblocks"
        else:
            best, gain = touched.most_common(1)[0]
            mode = "reduces_only"

        unblocked = (
            [trip for trip, items in remaining.items() if items == {best}]
            if mode == "unblocks"
            else []
        )

        ranking.append(
            {
                "blocker": best,
                "marginal_unblocked": len(unblocked),
                "trips_touching": touched[best],
                "mode": mode,
                "trips": sorted(unblocked)[:50],
                "still_blocked_after": len(remaining) - len(unblocked),
            }
        )

        for trip in unblocked:
            remaining.pop(trip, None)
        for items in remaining.values():
            items.discard(best)

    return ranking


def blocker_label(blocker: str, segments: dict, stations: dict) -> dict:
    if blocker.startswith("segment:"):
        _, a, b = blocker.split(":")
        key = tuple(sorted((a, b)))
        return {
            "kind": "segment",
            "from": key[0],
            "to": key[1],
            "quality": segments.get(key),
            "label": f"segment {key[0]}-{key[1]} ({segments.get(key)})",
        }
    code = blocker.split(":", 1)[1]
    return {
        "kind": "station",
        "code": code,
        "coord_status": stations.get(code),
        "label": f"station {code} ({stations.get(code)})",
    }


def main() -> int:
    if not DB.exists():
        print("build the database first")
        return 2
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = load_rows(connection)
        per_trip_segments = trip_segments(connection)
        segments = segment_quality(connection)
        stations = station_status(connection)
    finally:
        connection.close()

    by_reason: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        reason = reason_of(row)
        if reason:
            by_reason[reason][f"book{row['book']}"] += 1

    # Blockers per hidden trip, only for geometry-blocked trips.
    blocked: dict[str, set[str]] = {}
    for row in rows:
        if row["status"] not in ("has_unmeasured", "has_fallback"):
            continue
        items: set[str] = set()
        for pair in per_trip_segments.get(row["trip_id"], []):
            quality = segments.get(pair)
            if quality in BLOCKING_QUALITIES:
                items.add(f"segment:{pair[0]}:{pair[1]}")
        # A station with no coordinate blocks any trip that passes through it and
        # could not bypass it.
        if not items:
            for pair in per_trip_segments.get(row["trip_id"], []):
                for code in pair:
                    if stations.get(code) not in ("accepted", "override"):
                        items.add(f"station:{code}")
        blocked[row["trip_id"]] = items

    ranking_by_book: dict[str, list[dict]] = {}
    for book in ("1", "2"):
        subset = {
            trip: items
            for trip, items in blocked.items()
            if any(r["trip_id"] == trip and str(r["book"]) == book for r in rows)
        }
        ranking_by_book[book] = [
            {**entry, **blocker_label(entry["blocker"], segments, stations)}
            for entry in greedy(subset)
        ]

    all_ranked = [
        {**entry, **blocker_label(entry["blocker"], segments, stations)}
        for entry in greedy(blocked)
    ]

    never_shown = [
        {
            "trip_id": row["trip_id"],
            "train_no": row["train_no"],
            "name": row["name"],
            "book": row["book"],
            "service_class": row["service_class"],
            "status": row["status"],
            "reason": reason_of(row),
            "relation": row["relation"],
        }
        for row in rows
        if not is_shown(row)
    ]

    payload = {
        "note": (
            "Report only. 'marginal_trips' is the number of trips that become "
            "showable when this ONE blocker is fixed, given the blockers already "
            "fixed by earlier greedy steps. Greedy, so the sum is not additive."
        ),
        "total_trips": len(rows),
        "shown_by_default": sum(1 for row in rows if is_shown(row)),
        "hidden_by_reason": {key: dict(value) for key, value in sorted(by_reason.items())},
        "top_blockers": all_ranked,
        "top_blockers_by_book": ranking_by_book,
        "never_shown": never_shown,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {OUT}")
    print(f"  total {payload['total_trips']}, shown {payload['shown_by_default']}")
    for reason, counts in payload["hidden_by_reason"].items():
        print(f"  hidden {reason}: {sum(counts.values())} {counts}")
    print("  top blockers:")
    for entry in all_ranked[:10]:
        print(
            f"    {entry['marginal_unblocked']:4d} unblocked, "
            f"{entry['trips_touching']:4d} touched  {entry['label']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
