"""P4: measure what each draft bridge candidate would actually change.

Report only. Nothing is applied. For each candidate, route the affected segments
with and without the synthetic bridge, using the same pins and reviews the real
build uses, and record the numbers.

Usage:
    python -m pipeline.bridge_probe
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import build_geometry as bg
from pipeline.rail_graph import Edge, haversine_m

OUT = Path("data/review/bridge_probe.json")

# The candidates worth measuring, from data/config/geometry_bridges.draft.yaml.
CANDIDATES = [
    {
        "label": "BTT-CS seam",
        "from_node": 563692098,
        "to_node": 9794788929,
        "segments": [("BTT", "CS"), ("BOP", "BTT")],
    },
    {
        "label": "SB-SBI seam",
        "from_node": 14313928655,
        "to_node": 14313928656,
        "segments": [("SB", "SBI")],
    },
]


def build_graph(add_bridge: dict | None):
    config = bg.load_config()
    graph = bg.load_graph()
    graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(graph, bg.load_bridges())
    if add_bridge is not None:
        a, b = add_bridge["from_node"], add_bridge["to_node"]
        length = haversine_m(graph.coords[a], graph.coords[b])
        graph.adjacency.setdefault(a, []).append(Edge(a, b, length, 0))
        graph.adjacency.setdefault(b, []).append(Edge(b, a, length, 0))
        graph.way_of_edge[(a, b)] = 0
        graph.way_of_edge[(b, a)] = 0
        graph.service_of_edge[(a, b)] = "draft_bridge"
        graph.service_of_edge[(b, a)] = "draft_bridge"
    return graph, config


def route_segment(graph, config, accepted, pins, a: str, b: str) -> float | None:
    pin_a = pins.get(a)
    pin_b = pins.get(b)
    node_a = graph.snap(
        a,
        (accepted[a]["lat"], accepted[a]["lon"]),
        config["snap_accept_m"],
        config["snap_review_m"],
        pin_way=pin_a.way_id if pin_a else None,
    ).node_id
    node_b = graph.snap(
        b,
        (accepted[b]["lat"], accepted[b]["lon"]),
        config["snap_accept_m"],
        config["snap_review_m"],
        pin_way=pin_b.way_id if pin_b else None,
    ).node_id
    if node_a is None or node_b is None:
        return None
    result = bg.shortest_path(graph, node_a, node_b)
    return None if result is None else result[0]


def main() -> int:
    from pipeline import snap_pins

    accepted = bg.accepted_coordinates()
    pins = snap_pins.index(snap_pins.load())

    rows = []
    for candidate in CANDIDATES:
        baseline_graph, config = build_graph(None)
        bridged_graph, _ = build_graph(candidate)

        for a, b in candidate["segments"]:
            if a not in accepted or b not in accepted:
                continue
            without = route_segment(baseline_graph, config, accepted, pins, a, b)
            with_bridge = route_segment(bridged_graph, config, accepted, pins, a, b)
            straight = haversine_m(
                (accepted[a]["lat"], accepted[a]["lon"]),
                (accepted[b]["lat"], accepted[b]["lon"]),
            )
            rows.append(
                {
                    "candidate": candidate["label"],
                    "segment": f"{a}-{b}",
                    "straight_km": round(straight / 1000, 3),
                    "routed_without_km": None if without is None else round(without / 1000, 3),
                    "routed_with_km": None if with_bridge is None else round(with_bridge / 1000, 3),
                    "delta_km": None
                    if without is None or with_bridge is None
                    else round((with_bridge - without) / 1000, 3),
                    "detour_without": None if without is None else round(without / straight, 3),
                    "detour_with": None
                    if with_bridge is None
                    else round(with_bridge / straight, 3),
                }
            )

    payload = {
        "note": (
            "Report only. Each candidate is applied to a COPY of the graph to measure "
            "the effect; data/config/geometry_bridges.yaml is untouched."
        ),
        "candidates": CANDIDATES,
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {OUT}")
    for row in rows:
        print(
            f"  {row['candidate']:12s} {row['segment']:10s} straight {row['straight_km']} km | "
            f"without {row['routed_without_km']} km (detour {row['detour_without']}) | "
            f"with {row['routed_with_km']} km (detour {row['detour_with']}) | "
            f"delta {row['delta_km']} km"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
