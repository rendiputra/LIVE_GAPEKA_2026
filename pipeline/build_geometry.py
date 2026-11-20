"""Phase 4: route every consecutive station pair over the OSM rail network.

Deterministic. A pair is routed once (undirected) and reused reversed for the
opposite direction. Quality tiers are explicit:

- ``osm_routed``    — a path was found; length from OSM.
- ``osm_suspect``   — routed but the detour ratio exceeds the configured limit.
- ``straight_line`` — both ends snapped, but no path exists on the network.
- ``unmeasured``    — at least one end has no accepted coordinate or is unsnapped.

Nothing is silently routed and no geometry is invented.

Usage:
    python -m pipeline.build_geometry
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from pipeline.rail_graph import RailGraph, haversine_m

PARSED = Path("data/parsed")
EXTERNAL = Path("data/external")
REVIEW = Path("data/review")
DB = Path("data/gapeka.db")
CONFIG = Path("data/config/geometry.yaml")
OUT = PARSED / "segments.json"

DEFAULT_CONFIG = {
    "snap_accept_m": 300.0,
    "snap_review_m": 1000.0,
    "detour_suspect_ratio": 1.6,
    "implausible_fast_kmh": 160.0,
    "implausible_slow_kmh": 10.0,
    "gap_bridge_m": 25.0,
}


def load_config(path: Path = CONFIG) -> dict:
    config = dict(DEFAULT_CONFIG)
    if not path.exists():
        return config
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in config and value.strip().replace(".", "", 1).replace("-", "", 1).isdigit():
            config[key] = float(value.strip())
    return config


def load_graph() -> RailGraph:
    payload = json.loads((EXTERNAL / "java_rail_graph.json").read_text(encoding="utf-8"))
    coords = {item["id"]: (item["lat"], item["lon"]) for item in payload["node_coords"]}
    return RailGraph.from_ways(payload["ways"], coords)


def accepted_coordinates() -> dict[str, dict]:
    path = PARSED / "station_coordinates.json"
    if not path.exists():
        return {}
    matched = json.loads(path.read_text(encoding="utf-8"))["matched"]
    # A station with a rejected coordinate must not be routed.
    rejected = REVIEW / "stations_suspicious_coords.json"
    if rejected.exists():
        for row in json.loads(rejected.read_text(encoding="utf-8"))["stations"]:
            for code in row["code"].split(","):
                matched.pop(code.strip(), None)
    return matched


def trips() -> list[dict]:
    out = []
    for book, name in ((1, "intercity_trips.json"), (2, "local_trips.json")):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            train.setdefault("book", book)
            out.append(train)
    return out


def shortest_path(graph: RailGraph, start: int, goal: int) -> tuple[float, list[int]] | None:
    """BFS on hop count, then Dijkstra-style relaxation by length.

    The rail network is small per component; a bounded Dijkstra over a deque of
    priority buckets keeps this dependency-free while returning the shortest
    metric path.
    """
    import heapq

    dist: dict[int, float] = {start: 0.0}
    previous: dict[int, int] = {}
    heap: list[tuple[float, int]] = [(0.0, start)]
    seen: set[int] = set()

    while heap:
        cost, node = heapq.heappop(heap)
        if node in seen:
            continue
        seen.add(node)
        if node == goal:
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return cost, list(reversed(path))
        for edge in graph.adjacency.get(node, []):
            if edge.b in seen:
                continue
            new_cost = cost + edge.length_m
            if new_cost < dist.get(edge.b, float("inf")):
                dist[edge.b] = new_cost
                previous[edge.b] = node
                heapq.heappush(heap, (new_cost, edge.b))
    return None


def build(config: dict) -> dict:
    started = time.time()
    graph = load_graph()
    bridged = graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    coordinates = accepted_coordinates()

    # Snap every station with an accepted coordinate.
    snaps: dict[str, dict] = {}
    band_counts: Counter[str] = Counter()
    for code, entry in sorted(coordinates.items()):
        result = graph.snap(
            code,
            (entry["lat"], entry["lon"]),
            config["snap_accept_m"],
            config["snap_review_m"],
        )
        snaps[code] = result.as_dict()
        band_counts[result.band] += 1

    # Distinct undirected pairs needed by any trip.
    pairs: set[tuple[str, str]] = set()
    trip_pairs: dict[str, list[tuple[str, str]]] = {}
    for train in trips():
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        sequence = list(zip(codes, codes[1:], strict=False))
        trip_pairs[f"{train['book']}:{train['train_no']}"] = sequence
        for a, b in sequence:
            if a != b:
                pairs.add((a, b) if a < b else (b, a))

    # Route each undirected pair once.
    segments: dict[tuple[str, str], dict] = {}
    route_cache: dict[tuple[int, int], tuple[float, list[int]] | None] = {}

    for a, b in sorted(pairs):
        snap_a, snap_b = snaps.get(a), snaps.get(b)
        if not snap_a or not snap_b or snap_a["node_id"] is None or snap_b["node_id"] is None:
            segments[(a, b)] = {
                "from_code": a,
                "to_code": b,
                "quality": "unmeasured",
                "reason": "no snapped node for one or both ends",
                "length_m": None,
                "straight_m": None,
                "detour_ratio": None,
                "geometry": None,
            }
            continue

        na, nb = snap_a["node_id"], snap_b["node_id"]
        straight = haversine_m((snap_a["lat"], snap_a["lon"]), (snap_b["lat"], snap_b["lon"]))

        key = (na, nb) if na < nb else (nb, na)
        if key not in route_cache:
            route_cache[key] = shortest_path(graph, key[0], key[1])
        route = route_cache[key]

        if route is None:
            segments[(a, b)] = {
                "from_code": a,
                "to_code": b,
                "quality": "straight_line",
                "reason": "no path on the OSM rail network",
                "length_m": round(straight, 1),
                "straight_m": round(straight, 1),
                "detour_ratio": None,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [snap_a["lon"], snap_a["lat"]],
                        [snap_b["lon"], snap_b["lat"]],
                    ],
                },
            }
            continue

        length, path = route
        if key[0] != na:
            path = list(reversed(path))
        ratio = length / straight if straight > 0 else None
        suspect = ratio is not None and ratio > config["detour_suspect_ratio"]

        segments[(a, b)] = {
            "from_code": a,
            "to_code": b,
            "quality": "osm_suspect" if suspect else "osm_routed",
            "reason": (
                f"detour ratio {ratio:.2f} exceeds {config['detour_suspect_ratio']}"
                if suspect
                else ""
            ),
            "length_m": round(length, 1),
            "straight_m": round(straight, 1),
            "detour_ratio": None if ratio is None else round(ratio, 3),
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [round(graph.coords[n][1], 6), round(graph.coords[n][0], 6)] for n in path
                ],
            },
        }

    quality_counts = Counter(seg["quality"] for seg in segments.values())

    # Per-trip geometry status.
    trip_status: dict[str, dict] = {}
    for trip_key, sequence in trip_pairs.items():
        counts: Counter[str] = Counter()
        for a, b in sequence:
            if a == b:
                continue
            entry = segments.get((a, b) if a < b else (b, a))
            counts[entry["quality"] if entry else "unmeasured"] += 1
        if counts.get("unmeasured"):
            status = "has_unmeasured"
        elif counts.get("straight_line") or counts.get("osm_suspect"):
            status = "has_fallback"
        else:
            status = "complete"
        trip_status[trip_key] = {"status": status, "counts": dict(counts)}

    status_counts = Counter(v["status"] for v in trip_status.values())

    # Content hash over segments, independent of dict order.
    digest = hashlib.sha256()
    for key in sorted(segments):
        digest.update(json.dumps(segments[key], sort_keys=True).encode())

    payload = {
        "config": config,
        "graph": {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "gap_bridges": bridged,
        },
        "snap_bands": dict(band_counts),
        "snaps": snaps,
        "segments": [{"key": list(key), **segments[key]} for key in sorted(segments)],
        "quality_counts": dict(quality_counts),
        "trip_status": trip_status,
        "trip_status_counts": dict(status_counts),
        "content_hash": digest.hexdigest(),
        "runtime_seconds": round(time.time() - started, 1),
    }

    OUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    REVIEW.mkdir(parents=True, exist_ok=True)
    (REVIEW / "geometry_snaps.json").write_text(
        json.dumps(snaps, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build rail geometry for the MVP slice.")
    parser.parse_args(argv)
    config = load_config()
    payload = build(config)

    print(f"graph: {payload['graph']['nodes']:,} nodes, {payload['graph']['edges']:,} edges")
    print(f"snap bands: {payload['snap_bands']}")
    print(f"segments by quality: {payload['quality_counts']}")
    print(f"trips by status: {payload['trip_status_counts']}")
    print(f"content hash: {payload['content_hash']}")
    print(f"runtime: {payload['runtime_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
