"""Q3: rail-path triple consistency for station coordinates.

The old test used STRAIGHT-LINE distances and produced false positives at
junctions (a train that turns back at a junction legitimately gives a large
ratio). This version uses the routed rail graph and the angle at B:

- ``d_rail(A,B) + d_rail(B,C)`` versus ``d_rail(A,C)``;
- the turn angle at B, computed from bearings;
- a very sharp turn-back (angle close to 180 degrees of reversal) is classified
  ``junction_turnback`` and reported as INFO, not as a failure.

Nothing is changed automatically.

Usage:
    python -m pipeline.triple_rail
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from pipeline import build_geometry as bg
from pipeline.rail_graph import haversine_m

OUT = Path("data/review/q3_triple_rail.json")

RATIO_LIMIT = 1.15
# A reversal sharper than this is treated as a legitimate junction turn-back.
TURNBACK_ANGLE_DEG = 150.0


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def turn_angle(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Angle at B between B->A and B->C, in degrees (0 = straight through)."""
    b1 = bearing_deg(b, a)
    b2 = bearing_deg(b, c)
    diff = abs(b1 - b2) % 360
    return 360 - diff if diff > 180 else diff


def neighbour_map() -> dict[str, Counter]:
    out: dict[str, Counter] = {}
    for train in bg.trips():
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        for i, code in enumerate(codes):
            bucket = out.setdefault(code, Counter())
            if i > 0:
                bucket[codes[i - 1]] += 1
            if i + 1 < len(codes):
                bucket[codes[i + 1]] += 1
    return out


def write_comparison(payload: dict) -> dict | None:
    """Compare the rail-path result with the superseded straight-line test.

    Written to ``data/review/q3_vs_a3.json`` so every "false positive cleared"
    figure in a report has a file behind it. Report only; nothing is applied.
    """
    old_path = Path("data/review/a3_coord_hygiene.json")
    if not old_path.exists():
        return None
    old = json.loads(old_path.read_text(encoding="utf-8")).get("triple_failures", [])
    failing = {row["code"] for row in payload["failures"]}
    turnback = {row["code"] for row in payload["junction_turnbacks"]}
    old_codes = {row["code"] for row in old}
    cleared = sorted(code for code in old_codes if code not in failing and code not in turnback)

    comparison = {
        "note": (
            "Comparison of the old straight-line triple test (a3_coord_hygiene.json) "
            "with the rail-path test (q3_triple_rail.json). Report only."
        ),
        "old_straight_line_entries": len(old),
        "old_unique_codes": len(old_codes),
        "rail_ok": payload["counts"].get("ok", 0),
        "rail_failures": payload["counts"].get("failure", 0),
        "rail_junction_turnbacks": payload["counts"].get("junction_turnback", 0),
        "old_flagged_now_ok": cleared,
        "old_flagged_now_ok_count": len(cleared),
        "old_flagged_still_failing": sorted(old_codes & failing),
        "new_failures_not_previously_flagged": sorted(failing - old_codes),
    }
    Path("data/review/q3_vs_a3.json").write_text(
        json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
    )
    return comparison


def main() -> int:
    config = bg.load_config()
    graph = bg.load_graph()
    graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(graph, bg.load_bridges())
    coordinates = bg.accepted_coordinates()
    neighbours = neighbour_map()

    snaps = {
        code: graph.snap(
            code,
            (entry["lat"], entry["lon"]),
            config["snap_accept_m"],
            config["snap_review_m"],
        )
        for code, entry in coordinates.items()
    }

    path_cache: dict[tuple[int, int], float | None] = {}

    def rail_distance(a: str, b: str) -> float | None:
        sa, sb = snaps.get(a), snaps.get(b)
        if not sa or not sb or sa.node_id is None or sb.node_id is None:
            return None
        key = (sa.node_id, sb.node_id) if sa.node_id < sb.node_id else (sb.node_id, sa.node_id)
        if key not in path_cache:
            result = bg.shortest_path(graph, key[0], key[1])
            path_cache[key] = result[0] if result else None
        return path_cache[key]

    results = []
    counts: Counter[str] = Counter()

    for code in sorted(coordinates):
        adjacent = [
            n for n, _ in neighbours.get(code, Counter()).most_common(3) if n in coordinates
        ]
        point = (coordinates[code]["lat"], coordinates[code]["lon"])
        for i in range(len(adjacent)):
            for j in range(i + 1, len(adjacent)):
                a, c = adjacent[i], adjacent[j]
                direct = rail_distance(a, c)
                via = (rail_distance(a, code), rail_distance(code, c))
                if direct is None or None in via or direct <= 0:
                    continue
                ratio = (via[0] + via[1]) / direct
                angle = turn_angle(
                    (coordinates[a]["lat"], coordinates[a]["lon"]),
                    point,
                    (coordinates[c]["lat"], coordinates[c]["lon"]),
                )
                if ratio <= RATIO_LIMIT:
                    counts["ok"] += 1
                    continue

                classification = "junction_turnback" if angle >= TURNBACK_ANGLE_DEG else "failure"
                counts[classification] += 1
                results.append(
                    {
                        "code": code,
                        "name": coordinates[code]["name"],
                        "via": f"{a}-{code}-{c}",
                        "ratio": round(ratio, 3),
                        "turn_angle_deg": round(angle, 1),
                        "rail_direct_km": round(direct / 1000, 2),
                        "rail_via_km": round((via[0] + via[1]) / 1000, 2),
                        "straight_km": round(
                            haversine_m(
                                (coordinates[a]["lat"], coordinates[a]["lon"]),
                                (coordinates[c]["lat"], coordinates[c]["lon"]),
                            )
                            / 1000,
                            2,
                        ),
                        "classification": classification,
                    }
                )

    failures = sorted(
        (r for r in results if r["classification"] == "failure"),
        key=lambda r: -r["ratio"],
    )
    turnbacks = sorted(
        (r for r in results if r["classification"] == "junction_turnback"),
        key=lambda r: -r["ratio"],
    )

    payload = {
        "note": (
            "Rail-path triple consistency. Straight-line distance is reported for "
            "context only; the decision uses routed distances and the turn angle."
        ),
        "ratio_limit": RATIO_LIMIT,
        "turnback_angle_deg": TURNBACK_ANGLE_DEG,
        "counts": dict(counts),
        "failures": failures,
        "junction_turnbacks": turnbacks,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    comparison = write_comparison(payload)
    if comparison:
        print(
            f"old straight-line test: {comparison['old_straight_line_entries']} entries over "
            f"{comparison['old_unique_codes']} stations; cleared by the rail-path test: "
            f"{comparison['old_flagged_now_ok_count']}"
        )

    print(f"triples evaluated: {sum(counts.values())}  {dict(counts)}")
    print(f"failures: {len(failures)}  turnbacks(info): {len(turnbacks)}")
    for row in failures[:10]:
        print(
            f"  FAIL {row['code']:5s} {row['via']:20s} ratio={row['ratio']} "
            f"angle={row['turn_angle_deg']}"
        )
    for row in turnbacks[:5]:
        print(
            f"  TURN {row['code']:5s} {row['via']:20s} ratio={row['ratio']} "
            f"angle={row['turn_angle_deg']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
