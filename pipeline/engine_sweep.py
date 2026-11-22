"""R1: 24-hour sweep and benchmark for the position engine.

Sweeps 2026-12-01 at 60 s steps under the default policy and records:

- active trips per instant (peak, median);
- positions off-polyline (expected 0);
- continuity violations between consecutive samples of one trip;
- the share of legs whose cruise speed exceeds the printed maximum;
- trips excluded, by reason, per book;
- a timing benchmark for positions_at.

Usage:
    python -m pipeline.engine_sweep
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from engine.model import Policy
from engine.position import _legs, _point_on_trip, positions_at
from engine.snapshot import load
from pipeline.rail_graph import haversine_m

OUT = Path("data/review/r1_engine_sweep.json")
WIB = __import__("zoneinfo").ZoneInfo("Asia/Jakarta")
SWEEP_DATE = date(2026, 12, 1)
STEP_S = 60


def continuity_step(
    previous: dict[str, tuple[float, int]],
    by_trip: dict[str, list],
    second: int,
    max_mps: float = 120.0,
) -> tuple[list[dict], int]:
    """Compare one instant against the previous one; mutate ``previous``.

    Rules (all deliberate, because "0 violations" must mean something):

    - a trip_id appearing more than once at one instant is ambiguous (yesterday's
      run plus today's) and is skipped, with its tracker reset;
    - a tracker is dropped when its trip is absent, because a trip that reappears
      is a NEW run, not a jump;
    - only single-occurrence, continuous samples are compared.

    Returns ``(violations, ambiguous_count)``.
    """
    violations: list[dict] = []
    ambiguous = 0

    for trip_id, group in by_trip.items():
        if len(group) != 1:
            ambiguous += 1
            previous.pop(trip_id, None)
            continue
        position = group[0]
        prior = previous.get(trip_id)
        if prior is not None:
            prev_s, prev_t = prior
            if position.s_m < prev_s - 1.0:
                violations.append(
                    {
                        "trip_id": trip_id,
                        "t_s": second,
                        "from_m": round(prev_s, 1),
                        "to_m": round(position.s_m, 1),
                        "reason": "distance decreased",
                    }
                )
            implied = (position.s_m - prev_s) / max(1, second - prev_t)
            if implied > max_mps:
                violations.append(
                    {
                        "trip_id": trip_id,
                        "t_s": second,
                        "implied_mps": round(implied, 1),
                        "reason": "implausible jump between samples",
                    }
                )
        previous[trip_id] = (position.s_m, second)

    for stale in [key for key in previous if key not in by_trip]:
        previous.pop(stale)

    return violations, ambiguous


def main() -> int:
    started = time.time()
    snapshot = load()
    policy = Policy()

    active_counts = []
    off_polyline = 0
    continuity = []
    ambiguous_skipped = 0

    trips_by_id = {trip.trip_id: trip for trip in snapshot.trips}
    previous: dict[str, tuple[float, int]] = {}

    for second in range(0, 86400, STEP_S):
        instant = datetime(
            SWEEP_DATE.year, SWEEP_DATE.month, SWEEP_DATE.day, tzinfo=WIB
        ) + timedelta(seconds=second)
        positions = positions_at(snapshot, instant, policy)
        active_counts.append(len(positions))

        # positions_at scans several service dates, so ONE trip_id can appear
        # twice at one instant (yesterday's run still going plus today's run).
        # The rules live in continuity_step() and are unit-tested.
        by_trip: dict[str, list] = {}
        for position in positions:
            by_trip.setdefault(position.trip_id, []).append(position)

        for trip_id, group in by_trip.items():
            if len(group) != 1:
                continue
            position = group[0]
            # On-polyline check: recompute the point from s_m and compare.
            trip = trips_by_id.get(trip_id)
            if trip is not None:
                lat, lon = _point_on_trip(trip, position.s_m)
                if haversine_m((lat, lon), (position.lat, position.lon)) > 1.0:
                    off_polyline += 1

        found, ambiguous = continuity_step(previous, by_trip, second)
        continuity.extend(found)
        ambiguous_skipped += ambiguous

    # Leg cruise speed vs the PRINTED maximum speed (the PDF's Kecepatan column).
    # The printed value on a row applies to the stretch that row departs towards.
    printed_speed: dict[tuple[str, int], int | None] = {}
    connection = sqlite3.connect("file:data/gapeka.db?mode=ro", uri=True)
    try:
        for trip_id, seq, raw in connection.execute(
            "SELECT trip_id, seq, speed_raw FROM stop_times"
        ):
            value = None
            if raw is not None:
                text = str(raw).strip()
                if text.isdigit() and int(text) > 0:
                    value = int(text)
            printed_speed[(trip_id, seq)] = value
    finally:
        connection.close()

    fast_legs = []
    total_legs = 0
    legs_with_printed = 0
    ratio_buckets: dict[str, int] = {}

    def bucket(ratio: float) -> str:
        if ratio <= 1.0:
            return "<=1.00"
        if ratio <= 1.10:
            return "1.00-1.10"
        if ratio <= 1.25:
            return "1.10-1.25"
        if ratio <= 1.50:
            return "1.25-1.50"
        return ">1.50"

    for trip in snapshot.trips:
        for leg, a, b in _legs(trip, policy):
            total_legs += 1
            limit = printed_speed.get((trip.trip_id, a.seq))
            if limit is None:
                limit = printed_speed.get((trip.trip_id, b.seq))
            if limit is None:
                continue
            legs_with_printed += 1
            kmh = leg.cruise_mps * 3.6
            ratio = kmh / limit
            ratio_buckets[bucket(ratio)] = ratio_buckets.get(bucket(ratio), 0) + 1
            if kmh > limit * 1.10:  # >10% above the printed maximum
                fast_legs.append(
                    {
                        "trip_id": trip.trip_id,
                        "from": a.station_code,
                        "to": b.station_code,
                        "cruise_kmh": round(kmh, 1),
                        "printed_max_kmh": limit,
                        "ratio": round(ratio, 3),
                    }
                )

    # Exclusions by reason, per book. This must read the DATABASE, not the
    # snapshot: the snapshot has already dropped has_unmeasured trips, so
    # counting from it would always report zero and hide the real exclusion.
    from collections import Counter

    excluded: Counter = Counter()
    connection = sqlite3.connect("file:data/gapeka.db?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT t.book, t.service_class, g.status"
            " FROM trips t JOIN trip_geometry_status g ON g.trip_id = t.trip_id"
        ).fetchall()
    finally:
        connection.close()

    total_trips = len(rows)
    for book, service_class, status in rows:
        if status == "has_unmeasured":
            excluded[f"book{book}:has_unmeasured"] += 1
        elif status == "has_fallback" and policy.geometry_policy != "allow_fallback":
            excluded[f"book{book}:has_fallback_hidden"] += 1
        elif service_class == "fakultatif" and not policy.show_fakultatif:
            excluded[f"book{book}:fakultatif_hidden"] += 1
        elif service_class not in ("reguler", "fakultatif"):
            excluded[f"book{book}:unknown_class"] += 1

    shown = total_trips - sum(excluded.values())

    # Benchmark.
    query = datetime(2026, 12, 1, 8, 0, tzinfo=WIB)
    timings = []
    for _ in range(20):
        t0 = time.perf_counter()
        positions_at(snapshot, query, policy)
        timings.append((time.perf_counter() - t0) * 1000)

    payload = {
        "date": SWEEP_DATE.isoformat(),
        "step_s": STEP_S,
        "policy": policy.as_dict(),
        "snapshot": snapshot.as_dict(),
        "active": {
            "peak": max(active_counts),
            "median": int(statistics.median(active_counts)),
            "samples": len(active_counts),
        },
        # 00:00-05:00 is where previous-service-date tails live. Reporting it
        # separately makes them visible instead of averaging them away.
        "active_00_05": {
            "peak": max(active_counts[: 5 * 60]),
            "median": int(statistics.median(active_counts[: 5 * 60])),
            "min": min(active_counts[: 5 * 60]),
            "samples": len(active_counts[: 5 * 60]),
        },
        "active_per_hour": [
            {
                "hour": hour,
                "peak": max(active_counts[hour * 60 : (hour + 1) * 60]),
                "median": int(statistics.median(active_counts[hour * 60 : (hour + 1) * 60])),
            }
            for hour in range(24)
        ],
        "off_polyline_positions": off_polyline,
        "continuity_violations": len(continuity),
        "continuity_method": (
            "Trackers are kept per trip_id and are (a) reset when a trip_id "
            "appears twice at one instant (yesterday's run plus today's) and "
            "(b) dropped when a trip is absent for a step, because a trip that "
            "reappears is a new run rather than a jump. Only continuous, "
            "single-occurrence samples are compared."
        ),
        "continuity_ambiguous_skipped": ambiguous_skipped,
        "continuity_examples": continuity[:20],
        "legs": {
            "total": total_legs,
            "with_printed_max": legs_with_printed,
            "over_printed_max_10pct": len(fast_legs),
            "cruise_to_printed_ratio_buckets": dict(sorted(ratio_buckets.items())),
        },
        "fast_leg_examples": fast_legs[:20],
        "excluded": dict(excluded),
        "trips_total": total_trips,
        "trips_shown_by_default": shown,
        "benchmark_ms": {
            "median": round(statistics.median(timings), 2),
            "p95": round(sorted(timings)[int(len(timings) * 0.95) - 1], 2),
            "max": round(max(timings), 2),
            "runs": len(timings),
        },
        "runtime_s": round(time.time() - started, 1),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "active_peak": payload["active"]["peak"],
                "active_median": payload["active"]["median"],
                "active_00_05_peak": payload["active_00_05"]["peak"],
                "active_00_05_median": payload["active_00_05"]["median"],
                "off_polyline": off_polyline,
                "continuity": len(continuity),
                "continuity_ambiguous_skipped": ambiguous_skipped,
                "legs_over_printed_max": len(fast_legs),
                "legs_total": total_legs,
                "ratio_buckets": dict(sorted(ratio_buckets.items())),
                "benchmark_ms": payload["benchmark_ms"],
                "runtime_s": payload["runtime_s"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
