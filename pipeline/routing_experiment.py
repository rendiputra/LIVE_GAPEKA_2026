"""A5: compare default routing with service-weighted routing.

Costs affect path CHOICE only; every reported length stays the real geometric
distance, so a changed length means a genuinely different path.

Usage:
    python -m pipeline.routing_experiment
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import build_geometry as bg

OUT = Path("data/review/a5_routing_experiment.json")

DEFAULT_COSTS = {
    "mainline": 1.0,
    "siding": 1.0,
    "crossover": 1.0,
    "spur": 1.0,
    "yard": 4.0,
    "gap_bridge": 1.0,
}
WEIGHTED_COSTS = {
    "mainline": 1.0,
    "siding": 2.5,
    "crossover": 2.5,
    "spur": 3.0,
    "yard": 6.0,
    "gap_bridge": 1.0,
}


def build_graph(config: dict):
    graph = bg.load_graph()
    graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    return graph


def snap_all(graph, coordinates: dict, config: dict) -> dict:
    return {
        code: graph.snap(
            code, (entry["lat"], entry["lon"]), config["snap_accept_m"], config["snap_review_m"]
        )
        for code, entry in coordinates.items()
    }


def route_pairs(graph, snaps, pairs, costs) -> dict:
    """Route each undirected pair with the given cost model."""
    out = {}
    for a, b in sorted(pairs):
        sa, sb = snaps.get(a), snaps.get(b)
        if not sa or not sb or sa.node_id is None or sb.node_id is None:
            out[(a, b)] = {"quality": "unmeasured", "length_m": None}
            continue
        na, nb = sa.node_id, sb.node_id
        key = (na, nb) if na < nb else (nb, na)
        result = bg.shortest_path(graph, key[0], key[1], costs)
        if result is None:
            out[(a, b)] = {"quality": "straight_line", "length_m": None}
            continue
        length, path = result
        if key[0] != na:
            path = list(reversed(path))
        service = bg.path_service_counts(graph, path)
        total = sum(service.values()) or 1
        special = service.get("siding", 0) + service.get("crossover", 0) + service.get("spur", 0)
        out[(a, b)] = {
            "quality": "osm_routed",
            "length_m": length,
            "special_share": round(special / total, 4),
            "service": service,
        }
    return out


def summarise(routes: dict) -> dict:
    shares = sorted(
        r["special_share"] for r in routes.values() if r.get("special_share") is not None
    )
    lengths = [r["length_m"] for r in routes.values() if r.get("length_m")]
    return {
        "routed": sum(1 for r in routes.values() if r["quality"] == "osm_routed"),
        "straight_line": sum(1 for r in routes.values() if r["quality"] == "straight_line"),
        "unmeasured": sum(1 for r in routes.values() if r["quality"] == "unmeasured"),
        "share_p50": shares[len(shares) // 2] if shares else None,
        "share_p90": shares[int(len(shares) * 0.9)] if shares else None,
        "share_max": shares[-1] if shares else None,
        "total_km": round(sum(lengths) / 1000, 1),
    }


def main() -> int:
    config = bg.load_config()
    coordinates = bg.accepted_coordinates()

    graph = build_graph(config)
    snaps = snap_all(graph, coordinates, config)

    pairs = set()
    for train in bg.trips():
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        for a, b in zip(codes, codes[1:], strict=False):
            if a != b:
                pairs.add((a, b) if a < b else (b, a))

    default_routes = route_pairs(graph, snaps, pairs, DEFAULT_COSTS)
    weighted_routes = route_pairs(graph, snaps, pairs, WEIGHTED_COSTS)

    changed = []
    for pair in sorted(pairs):
        d = default_routes[pair].get("length_m")
        w = weighted_routes[pair].get("length_m")
        if d and w and abs(w - d) / d > 0.05:
            changed.append(
                {
                    "pair": f"{pair[0]}->{pair[1]}",
                    "default_km": round(d / 1000, 2),
                    "weighted_km": round(w / 1000, 2),
                    "delta_pct": round((w - d) / d * 100, 1),
                }
            )

    top_default = sorted(
        (
            {"pair": f"{a}->{b}", **v}
            for (a, b), v in default_routes.items()
            if v.get("special_share")
        ),
        key=lambda r: -r["special_share"],
    )[:10]

    payload = {
        "note": (
            "Costs change path choice only. length_m is always the real geometric "
            "length, so a changed length means a different path was chosen."
        ),
        "costs": {"default": DEFAULT_COSTS, "weighted": WEIGHTED_COSTS},
        "pairs": len(pairs),
        "default": summarise(default_routes),
        "weighted": summarise(weighted_routes),
        "changed_over_5pct": changed,
        "changed_count": len(changed),
        "top_share_default": top_default,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"pairs: {len(pairs)}")
    print(f"default : {payload['default']}")
    print(f"weighted: {payload['weighted']}")
    print(f"changed >5%: {len(changed)}")
    for row in changed[:10]:
        print(
            f"  {row['pair']:12s} {row['default_km']:>8} -> "
            f"{row['weighted_km']:>8} km ({row['delta_pct']}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
