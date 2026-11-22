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

from pipeline import segment_reviews, snap_pins
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
    "cost_mainline": 1.0,
    "cost_siding": 1.0,
    "cost_crossover": 1.0,
    "cost_spur": 1.0,
    "cost_yard": 4.0,
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


def load_bridges(path: Path = Path("data/config/geometry_bridges.yaml")) -> list[dict]:
    """Parse the human-authored bridge file (Q1)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if "bridges:" not in text:
        return []
    block = text.split("bridges:", 1)[1]
    bridges: list[dict] = []
    current: dict | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- pair:"):
            current = {}
            bridges.append(current)
            continue
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip('"')
        if key in ("from_node", "to_node"):
            current[key] = int(value)
        elif key in ("reason", "evidence", "decided_by", "date"):
            current[key] = value
    return [b for b in bridges if "from_node" in b and "to_node" in b]


def apply_bridges(graph: RailGraph, bridges: list[dict]) -> int:
    """Add a synthetic edge for each human-approved bridge. Returns the count."""
    from pipeline.rail_graph import Edge, haversine_m

    applied = 0
    for bridge in bridges:
        a, b = bridge["from_node"], bridge["to_node"]
        if a not in graph.coords or b not in graph.coords:
            continue
        if any(edge.b == b for edge in graph.adjacency.get(a, [])):
            continue
        length = haversine_m(graph.coords[a], graph.coords[b])
        graph.adjacency.setdefault(a, []).append(Edge(a, b, length, 0))
        graph.adjacency.setdefault(b, []).append(Edge(b, a, length, 0))
        graph.way_of_edge[(a, b)] = 0
        graph.way_of_edge[(b, a)] = 0
        graph.service_of_edge[(a, b)] = "human_bridge"
        graph.service_of_edge[(b, a)] = "human_bridge"
        applied += 1
    return applied


def load_graph(name: str = "java_rail_graph.json") -> RailGraph:
    payload = json.loads((EXTERNAL / name).read_text(encoding="utf-8"))
    coords = {item["id"]: (item["lat"], item["lon"]) for item in payload["node_coords"]}
    return RailGraph.from_ways(payload["ways"], coords)


def rejected_codes(path: Path | None = None) -> set[str]:
    """Codes excluded by tracked config (P2), not by a gitignored review artefact.

    ``data/config/rejected_stations.yaml`` is human-authored and committed, so a
    clean clone reproduces the same exclusions. A code listed here is not routed
    unless a human override supersedes it.
    """
    path = path or Path("data/config/rejected_stations.yaml")
    if not path.exists():
        return set()
    # Every listed code is a rejected coordinate, whether it appears under
    # `rejected:` or under `evidence:`; a human override still supersedes it.
    return {row["code"] for row in rejected_evidence(path) if row.get("code")}


def rejected_evidence(path: Path | None = None) -> list[dict]:
    """Every rejected-coordinate evidence row from tracked config (P2)."""
    path = path or Path("data/config/rejected_stations.yaml")
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if "evidence:" not in text:
        return []
    rows: list[dict] = []
    current: dict | None = None
    for line in text.split("evidence:", 1)[1].splitlines():
        stripped = line.strip()
        if stripped.startswith("- code:"):
            current = {"code": stripped.split(":", 1)[1].strip().strip('"')}
            rows.append(current)
            continue
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip('"')
        if key in ("lat", "lon"):
            try:
                current[key] = float(value)
            except ValueError:
                pass
        elif key in ("source", "source_id", "reason", "status", "decided_by", "date", "retrieved"):
            current[key] = value
    return rows


def accepted_coordinates() -> dict[str, dict]:
    """Coordinates usable for geometry: external matches plus human overrides.

    Human overrides win, and a rejected coordinate never reaches this function.
    """
    from pipeline.station_overrides import apply_to
    from pipeline.station_overrides import load as load_overrides

    path = PARSED / "station_coordinates.json"
    matched = json.loads(path.read_text(encoding="utf-8"))["matched"] if path.exists() else {}
    overrides = load_overrides()
    if overrides:
        matched = apply_to(overrides, matched)
    # A rejected coordinate must not be routed, but a human override supersedes
    # the rejection: the override IS the correction.
    override_codes = {o.code for o in overrides}
    for code in rejected_codes():
        if code not in override_codes:
            matched.pop(code, None)
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


def path_service_counts(graph: RailGraph, path: list[int]) -> dict[str, int]:
    """Count the OSM ``service`` class of each hop in a routed path.

    Needed to show how much of the network relies on sidings/crossovers, which
    are kept for connectivity but can create visual artefacts.
    """
    counts: dict[str, int] = {}
    for a, b in zip(path, path[1:], strict=False):
        service = graph.service_of_edge.get((a, b), "unknown")
        counts[service] = counts.get(service, 0) + 1
    return counts


def shortest_path(
    graph: RailGraph,
    start: int,
    goal: int,
    costs: dict[str, float] | None = None,
) -> tuple[float, list[int]] | None:
    """Dijkstra over geometric length, optionally weighted by service class.

    ``costs`` multiplies an edge's LENGTH for path CHOICE only. The returned
    length is always the real geometric distance, so reported km never depend on
    the experiment's weights.
    """
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
    real_length: dict[int, float] = {start: 0.0}

    while heap:
        cost, node = heapq.heappop(heap)
        if node in seen:
            continue
        seen.add(node)
        if node == goal:
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            path.reverse()
            # Report the real geometric length, never the weighted cost.
            total = sum(graph.edge_length(a, b) for a, b in zip(path, path[1:], strict=False))
            return total, path
        for edge in graph.adjacency.get(node, []):
            if edge.b in seen:
                continue
            weight = 1.0
            if costs:
                weight = costs.get(graph.service_of_edge.get((edge.a, edge.b), "mainline"), 1.0)
            new_cost = cost + edge.length_m * weight
            if new_cost < dist.get(edge.b, float("inf")):
                dist[edge.b] = new_cost
                real_length[edge.b] = real_length.get(node, 0.0) + edge.length_m
                previous[edge.b] = node
                heapq.heappush(heap, (new_cost, edge.b))
    return None


def build(
    config: dict,
    graph_file: str = "java_rail_graph.json",
    baseline: bool = False,
    out_path: Path | None = None,
) -> dict:
    """Build segments.

    ``baseline=True`` reproduces the state BEFORE Q1 (human bridges) and Q4
    (waypoint bypass). It exists only to generate an honest before/after
    comparison; it never writes ``data/parsed/segments.json``.
    """
    started = time.time()
    graph = load_graph(graph_file)
    bridged = graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    human_bridges = [] if baseline else load_bridges()
    human_bridged = apply_bridges(graph, human_bridges)
    # Human segment reviews (ADR 005). Ignored in baseline mode so the
    # before/after comparison stays about Q1/Q4.
    reviews = [] if baseline else segment_reviews.load()
    review_index = segment_reviews.index(reviews)
    # Q1a snap pins: a human says which track a station is on. Ignored in
    # baseline mode so the pre-Q1 state stays reproducible.
    pins = [] if baseline else snap_pins.load()
    pin_index = snap_pins.index(pins)
    coordinates = accepted_coordinates()

    # Snap every station with an accepted coordinate.
    snaps: dict[str, dict] = {}
    band_counts: Counter[str] = Counter()
    pins_applied: dict[str, dict] = {}
    pins_unusable: list[dict] = []
    for code, entry in sorted(coordinates.items()):
        pin = pin_index.get(code)
        result = graph.snap(
            code,
            (entry["lat"], entry["lon"]),
            config["snap_accept_m"],
            config["snap_review_m"],
            pin_way=pin.way_id if pin else None,
        )
        snaps[code] = result.as_dict()
        band_counts[result.band] += 1
        if pin is not None:
            if result.band == "ok_pinned":
                pins_applied[code] = {
                    "way_id": pin.way_id,
                    "snap_distance_m": round(result.snap_distance_m or 0.0, 1),
                    "decided_by": pin.decided_by,
                }
            else:
                pins_unusable.append(
                    {
                        "station": code,
                        "way_id": pin.way_id,
                        "snap_distance_m": None
                        if result.snap_distance_m is None
                        else round(result.snap_distance_m, 1),
                        "band": result.band,
                        "reason": "pin farther than snap_accept_m; normal snap used",
                    }
                )

    # Distinct undirected pairs needed by any trip.
    #
    # Q4 bypass rule: a row may be skipped when (a) its stop_type is pass or
    # unknown_untimed, (b) its station has no accepted coordinate, (c) the
    # neighbouring rows HAVE coordinates, and (d) at most 3 consecutive rows are
    # bypassed. A `stop` row is NEVER bypassed.
    MAX_BYPASS_RUN = 3
    pairs: set[tuple[str, str]] = set()
    trip_pairs: dict[str, list[tuple[str, str]]] = {}
    trip_bypass: dict[str, list[dict]] = {}

    for train in trips():
        rows = [s for s in train["stops"] if s["station_code"]]
        trip_key = f"{train['book']}:{train['train_no']}"
        located = [bool(s["station_code"] in coordinates) for s in rows]

        # Find runs of bypassable rows.
        bypassed: set[int] = set()
        index = 0
        while index < len(rows):
            if located[index]:
                index += 1
                continue
            start = index
            while index < len(rows) and not located[index]:
                index += 1
            end = index  # exclusive
            run = list(range(start, end))
            # Neighbours must exist and have coordinates.
            left_ok = start - 1 >= 0 and located[start - 1]
            right_ok = end < len(rows) and located[end]
            if baseline or not (left_ok and right_ok) or len(run) > MAX_BYPASS_RUN:
                continue
            if any(rows[i]["stop_type"] not in ("pass", "unknown_untimed") for i in run):
                continue
            bypassed.update(run)

        sequence: list[tuple[str, str]] = []
        previous_index: int | None = None
        for i, row in enumerate(rows):
            if i in bypassed:
                continue
            if previous_index is not None:
                a = rows[previous_index]["station_code"]
                b = row["station_code"]
                if a != b:
                    sequence.append((a, b))
            previous_index = i

        trip_pairs[trip_key] = sequence
        if bypassed:
            trip_bypass[trip_key] = [
                {
                    "seq": rows[i]["seq"],
                    "station_code": rows[i]["station_code"],
                    "stop_type": rows[i]["stop_type"],
                }
                for i in sorted(bypassed)
            ]
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

        service_counts = path_service_counts(graph, path)
        special = (
            service_counts.get("siding", 0)
            + service_counts.get("crossover", 0)
            + service_counts.get("spur", 0)
        )
        total_hops = sum(service_counts.values()) or 1

        base_quality = "osm_suspect" if suspect else "osm_routed"
        review = review_index.get((a, b))
        quality, review_note = segment_reviews.apply_quality(base_quality, review)
        reason = (
            f"detour ratio {ratio:.2f} exceeds {config['detour_suspect_ratio']}" if suspect else ""
        )
        if review_note:
            reason = f"{reason}; {review_note}" if reason else review_note

        segments[(a, b)] = {
            "from_code": a,
            "to_code": b,
            "quality": quality,
            "service_counts": service_counts,
            "special_service_share": round(special / total_hops, 4),
            "reason": reason,
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
            # osm_routed_reviewed is deliberately NOT here: a human accepted the
            # route, so it counts as complete (ADR 005).
            status = "has_fallback"
        elif trip_key in trip_bypass:
            status = "complete_estimated"
        else:
            status = "complete"
        trip_status[trip_key] = {
            "status": status,
            "counts": dict(counts),
            "has_bypassed_waypoints": trip_key in trip_bypass,
            "bypassed": trip_bypass.get(trip_key, []),
        }

    status_counts = Counter(v["status"] for v in trip_status.values())

    # Content hash over segments, independent of dict order.
    digest = hashlib.sha256()
    for key in sorted(segments):
        digest.update(json.dumps(segments[key], sort_keys=True).encode())

    # Per-trip length, computed ONLY from the segments table.
    trip_lengths: dict[str, float | None] = {}
    for trip_key, sequence in trip_pairs.items():
        total = 0.0
        complete = True
        for a, b in sequence:
            if a == b:
                continue
            entry = segments.get((a, b) if a < b else (b, a))
            if entry is None or entry["length_m"] is None:
                complete = False
                break
            total += entry["length_m"]
        trip_lengths[trip_key] = round(total, 1) if complete else None

    payload = {
        "config": config,
        "trip_lengths_m": trip_lengths,
        "graph": {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "gap_bridges": bridged,
            "human_bridges": human_bridged,
        },
        "snap_bands": dict(band_counts),
        "snaps": snaps,
        "segments": [{"key": list(key), **segments[key]} for key in sorted(segments)],
        "quality_counts": dict(quality_counts),
        "trip_status": trip_status,
        "trip_bypass": trip_bypass,
        "snap_pins_applied": pins_applied,
        "snap_pins_unusable": pins_unusable,
        "trip_status_counts": dict(status_counts),
        "content_hash": digest.hexdigest(),
        "runtime_seconds": round(time.time() - started, 1),
    }

    target = out_path or OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    REVIEW.mkdir(parents=True, exist_ok=True)
    if not baseline:
        (REVIEW / "geometry_snaps.json").write_text(
            json.dumps(snaps, indent=2) + "\n", encoding="utf-8"
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build rail geometry for the MVP slice.")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "reproduce the pre-Q1/Q4 state into data/review/t1_before.json (no bridges, no bypass)"
        ),
    )
    args = parser.parse_args(argv)
    config = load_config()
    if args.baseline:
        payload = build(config, baseline=True, out_path=REVIEW / "t1_before.json")
        print(f"BASELINE written to {REVIEW / 't1_before.json'}")
    else:
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
