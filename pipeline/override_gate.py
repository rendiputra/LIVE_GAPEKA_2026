"""Safety gate for a proposed station coordinate (H5, H6).

This is the rail-path version of the gate required for a new override:

1. the point is inside the Java bounding box;
2. it snaps to a rail edge within a per-call threshold;
3. the rail-path neighbour triple test passes
   (``d_rail(A,B) + d_rail(B,C) <= 1.15 * d_rail(A,C)``), using the routed
   graph rather than straight-line distances, with a sharp turn-back
   (>= 150 deg) classified ``junction_turnback`` and treated as info.

Nothing is applied here. Callers decide; this module only produces evidence.

Usage:
    python -m pipeline.override_gate TLM -6.257272 107.111231 --snap-max-m 300
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from pipeline import build_geometry as bg
from pipeline.rail_graph import haversine_m
from pipeline.triple_rail import RATIO_LIMIT, TURNBACK_MAX_ANGLE_DEG, turn_angle

JAVA_BBOX = {
    "min_lat": -9.2,
    "max_lat": -5.5,
    "min_lon": 105.0,
    "max_lon": 115.0,
}


def trip_neighbours() -> dict[str, Counter]:
    """How often each station appears next to each other station, across trips."""
    out: dict[str, Counter] = {}
    for train in bg.trips():
        codes = [row["station_code"] for row in train["stops"] if row["station_code"]]
        for index, code in enumerate(codes):
            bucket = out.setdefault(code, Counter())
            if index > 0:
                bucket[codes[index - 1]] += 1
            if index + 1 < len(codes):
                bucket[codes[index + 1]] += 1
    return out


def in_java(lat: float, lon: float) -> bool:
    return (
        JAVA_BBOX["min_lat"] <= lat <= JAVA_BBOX["max_lat"]
        and JAVA_BBOX["min_lon"] <= lon <= JAVA_BBOX["max_lon"]
    )


def evaluate(
    code: str,
    lat: float,
    lon: float,
    snap_max_m: float,
    *,
    graph=None,
    config=None,
    accepted=None,
    neighbours=None,
) -> dict:
    """Run the full gate for one proposed coordinate and return the evidence.

    The gate enumerates EVERY rail edge within ``snap_max_m`` and evaluates the
    rail-path triple for each, because ``snap()`` takes the geometrically nearest
    edge and on a double-track line that can be the wrong parallel track (a
    station between two tracks is within a few metres of both). A station whose
    nearest track routes 2.8x too far is a snap ambiguity, not a bad coordinate,
    so the gate reports both and refuses to pass on the lucky one alone.
    """
    config = config or bg.load_config()
    if graph is None:
        graph = bg.load_graph()
        graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
        bg.apply_bridges(graph, bg.load_bridges())
    accepted = accepted if accepted is not None else bg.accepted_coordinates()
    neighbours = neighbours if neighbours is not None else trip_neighbours()

    point = (lat, lon)

    # Enumerate candidate edges on a PRISTINE graph, before any split mutates it.
    from pipeline.rail_graph import project_point_to_segment

    candidates = []
    seen: set[tuple[int, int]] = set()
    for edges in graph.adjacency.values():
        for edge in edges:
            if edge.a > edge.b or (edge.a, edge.b) in seen:
                continue
            projected, distance, _t = project_point_to_segment(
                point, graph.coords[edge.a], graph.coords[edge.b]
            )
            if distance > snap_max_m:
                continue
            seen.add((edge.a, edge.b))
            candidates.append((distance, edge.a, edge.b, projected, edge.way_id))
    candidates.sort()

    snap = graph.snap(code, point, config["snap_accept_m"], config["snap_review_m"])

    # Rail distances need snapped nodes for the code and for its neighbours.
    snaps = dict()
    for other, entry in accepted.items():
        if other == code:
            continue
        snaps[other] = graph.snap(
            other,
            (entry["lat"], entry["lon"]),
            config["snap_accept_m"],
            config["snap_review_m"],
        )

    # Only neighbours that already have an accepted coordinate are usable.
    usable = [
        other for other, _ in neighbours.get(code, Counter()).most_common(4) if other in accepted
    ]

    def triple_for(node_id: int | None) -> dict:
        """Triple evidence when this code sits at ``node_id``."""
        path_cache: dict[tuple[int, int], float | None] = {}

        def rail(other: str) -> float | None:
            other_node = snaps[other].node_id if other in snaps else None
            if node_id is None or other_node is None:
                return None
            key = (node_id, other_node) if node_id < other_node else (other_node, node_id)
            if key not in path_cache:
                result = bg.shortest_path(graph, key[0], key[1])
                path_cache[key] = result[0] if result else None
            return path_cache[key]

        ratios = []
        for i, left in enumerate(usable):
            for right in usable[i + 1 :]:
                left_node = snaps[left].node_id if left in snaps else None
                right_node = snaps[right].node_id if right in snaps else None
                direct = None
                if left_node is not None and right_node is not None:
                    key = (
                        (left_node, right_node)
                        if left_node < right_node
                        else (right_node, left_node)
                    )
                    if key not in path_cache:
                        result = bg.shortest_path(graph, key[0], key[1])
                        path_cache[key] = result[0] if result else None
                    direct = path_cache[key]
                via_left = rail(left)
                via_right = rail(right)
                if direct is None or via_left is None or via_right is None or direct <= 0:
                    continue
                ratio = (via_left + via_right) / direct
                angle = turn_angle(
                    (accepted[left]["lat"], accepted[left]["lon"]),
                    point,
                    (accepted[right]["lat"], accepted[right]["lon"]),
                )
                # A genuine turn-back puts the two neighbours on the SAME side of
                # B, so the angle at B is SMALL (the human's own example
                # TGG-BBG-TGW is 20.4 deg). A station that sits BETWEEN its
                # neighbours gives an angle near 180 deg. Treating >= 150 deg as
                # a turn-back was inverted and hid real routing failures.
                classification = (
                    "junction_turnback" if angle <= TURNBACK_MAX_ANGLE_DEG else "ratio_check"
                )
                ratios.append(
                    {
                        "via": f"{left}-{code}-{right}",
                        "ratio": round(ratio, 3),
                        "turn_angle_deg": round(angle, 1),
                        "classification": classification,
                        "rail_direct_km": round(direct / 1000, 2),
                        "rail_via_km": round((via_left + via_right) / 1000, 2),
                        "straight_km": round(
                            haversine_m(
                                (accepted[left]["lat"], accepted[left]["lon"]),
                                (accepted[right]["lat"], accepted[right]["lon"]),
                            )
                            / 1000,
                            2,
                        ),
                    }
                )

        hard = [
            row
            for row in ratios
            if row["classification"] == "ratio_check" and row["ratio"] > RATIO_LIMIT
        ]
        usable_ratios = [row["ratio"] for row in ratios if row["classification"] == "ratio_check"]
        return {
            "triples": ratios,
            "worst_ratio": round(max(usable_ratios), 3) if usable_ratios else None,
            "hard_failures": hard,
            "evaluated": bool(ratios),
            "passes": not hard and bool(ratios),
        }

    nearest = triple_for(snap.node_id)

    # Evaluate every candidate track on ONE fresh copy: splitting distinct edges
    # is independent, so a single copy is correct and far cheaper than reloading.
    # Candidate edges come from the PRISTINE graph (above), so they never contain
    # a synthetic node created by the snap.
    local = bg.load_graph()
    local.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(local, bg.load_bridges())

    alternatives = []
    for distance, a, b, projected, way in candidates[:8]:
        if a not in local.coords or b not in local.coords:
            continue
        node = local._split_edge(a, b, projected)
        # Re-snap the neighbours on this copy so node ids stay valid.
        local_snaps = {}
        for other, entry in accepted.items():
            if other == code:
                continue
            local_snaps[other] = local.snap(
                other,
                (entry["lat"], entry["lon"]),
                config["snap_accept_m"],
                config["snap_review_m"],
            )

        ratios = []
        for i, left in enumerate(usable):
            for right in usable[i + 1 :]:
                ln = local_snaps.get(left)
                rn = local_snaps.get(right)
                if not ln or not rn or ln.node_id is None or rn.node_id is None:
                    continue
                d_ac = bg.shortest_path(local, ln.node_id, rn.node_id)
                d_lb = bg.shortest_path(local, ln.node_id, node)
                d_br = bg.shortest_path(local, node, rn.node_id)
                if not d_ac or not d_lb or not d_br or d_ac[0] <= 0:
                    continue
                ratio = (d_lb[0] + d_br[0]) / d_ac[0]
                angle = turn_angle(
                    (accepted[left]["lat"], accepted[left]["lon"]),
                    point,
                    (accepted[right]["lat"], accepted[right]["lon"]),
                )
                ratios.append(
                    {
                        "via": f"{left}-{code}-{right}",
                        "ratio": round(ratio, 3),
                        "turn_angle_deg": round(angle, 1),
                        "classification": (
                            "junction_turnback"
                            if angle <= TURNBACK_MAX_ANGLE_DEG
                            else "ratio_check"
                        ),
                    }
                )

        hard = [
            row
            for row in ratios
            if row["classification"] == "ratio_check" and row["ratio"] > RATIO_LIMIT
        ]
        alternatives.append(
            {
                "edge": [a, b],
                "way_id": way,
                "snap_distance_m": round(distance, 1),
                "triples": ratios,
                "passes": not hard and bool(ratios),
            }
        )

    alternatives.sort(key=lambda row: (not row["passes"], row["snap_distance_m"]))

    neighbour_distances = {
        other: round(haversine_m(point, (accepted[other]["lat"], accepted[other]["lon"])) / 1000, 3)
        for other in usable
    }

    checks = {
        "in_java": in_java(lat, lon),
        "snap_within_max": snap.snap_distance_m is not None and snap.snap_distance_m <= snap_max_m,
        "triple_evaluated": nearest["evaluated"],
        "nearest_edge_triple_passes": nearest["passes"],
    }
    # A disagreement between the nearest track and a nearby track means the
    # coordinate cannot be judged until a human picks the track.
    snap_ambiguous = bool(alternatives) and nearest["passes"] != alternatives[0]["passes"]
    checks["snap_ambiguous"] = snap_ambiguous

    passes = all(
        (
            checks["in_java"],
            checks["snap_within_max"],
            checks["triple_evaluated"],
            checks["nearest_edge_triple_passes"],
        )
    )
    if snap_ambiguous:
        passes = False

    return {
        "code": code,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "snap_max_m": snap_max_m,
        "snap": {
            "distance_m": None if snap.snap_distance_m is None else round(snap.snap_distance_m, 1),
            "band": snap.band,
            "node_id": snap.node_id,
            "edge": list(snap.edge) if snap.edge else None,
        },
        "neighbours_used": usable,
        "neighbour_straight_km": neighbour_distances,
        "triples": nearest["triples"],
        "worst_ratio": nearest["worst_ratio"],
        "ratio_limit": RATIO_LIMIT,
        "turnback_max_angle_deg": TURNBACK_MAX_ANGLE_DEG,
        "candidate_tracks": alternatives,
        "checks": checks,
        "passes": passes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rail-path safety gate for a proposed coordinate.")
    parser.add_argument("code")
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("--snap-max-m", type=float, default=300.0)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)

    result = evaluate(args.code, args.lat, args.lon, args.snap_max_m)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"{result['code']}: passes={result['passes']}")
        print(
            f"  snap {result['snap']['distance_m']} m (max {args.snap_max_m}), "
            f"band {result['snap']['band']}"
        )
        for row in result["triples"]:
            print(
                f"  {row['via']:22s} ratio {row['ratio']} "
                f"angle {row['turn_angle_deg']} ({row['classification']})"
            )
        print(f"  checks: {result['checks']}")
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
