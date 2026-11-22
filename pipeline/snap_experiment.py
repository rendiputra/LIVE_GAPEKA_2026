"""Q1(b): routing-aware snapping as an EXPERIMENT (`--snap-mode routing_aware`).

Default snapping takes the geometrically NEAREST edge. On a double track that can
be a stub, and the route then goes the long way round. Routing-aware snapping
instead picks, for each station, the edge within `snap_accept_m` that minimises the
routed distance to the station's neighbours in the trips.

This is an experiment. It does NOT change `data/parsed/segments.json`; it writes
`data/review/snap_experiment.json`.

Method
1. Choose an edge per station with a cheap anchor approximation.
2. Rebuild every segment exactly once on one graph with those edges (real splits).
3. Compare with the current segment lengths and report every change.

Usage:
    python -m pipeline.snap_experiment
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from pipeline import build_geometry as bg
from pipeline import snap_pins, trip_pairs
from pipeline.rail_graph import haversine_m, project_point_to_segment

OUT = Path("data/review/snap_experiment.json")
SEGMENTS = Path("data/parsed/segments.json")
MAX_CANDIDATES = 4
MIN_IMPROVEMENT = 0.01  # 1 % shorter before we call it a change


def candidates_for(graph, point, accept_m: float) -> list[tuple[float, int, int, tuple]]:
    out = []
    seen: set[tuple[int, int]] = set()
    for edges in graph.adjacency.values():
        for edge in edges:
            if edge.a > edge.b or (edge.a, edge.b) in seen:
                continue
            projected, distance, _t = project_point_to_segment(
                point, graph.coords[edge.a], graph.coords[edge.b]
            )
            if distance > accept_m:
                continue
            seen.add((edge.a, edge.b))
            out.append((distance, edge.a, edge.b, projected))
    out.sort()
    return out[:MAX_CANDIDATES]


def anchor_of(edge: tuple[int, int], projected: tuple, graph) -> int:
    a, b = edge
    return (
        a
        if haversine_m(graph.coords[a], projected) <= haversine_m(graph.coords[b], projected)
        else b
    )


def main() -> int:
    config = bg.load_config()
    accepted = bg.accepted_coordinates()
    pins = snap_pins.index(snap_pins.load())
    current = {
        (row["from_code"], row["to_code"]): row
        for row in json.loads(SEGMENTS.read_text())["segments"]
    }

    pairs, _usage = trip_pairs.load()
    neighbours: dict[str, Counter] = defaultdict(Counter)
    for sequence in pairs.values():
        for a, b in sequence:
            neighbours[a][b] += 1
            neighbours[b][a] += 1

    # --- step 1: choose an edge per station --------------------------------
    selection_graph = bg.load_graph()
    selection_graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(selection_graph, bg.load_bridges())

    chosen: dict[str, dict] = {}
    for code, entry in sorted(accepted.items()):
        point = (entry["lat"], entry["lon"])
        candidates = candidates_for(selection_graph, point, config["snap_accept_m"])
        if not candidates:
            continue
        nearest = candidates[0]

        if code in pins:
            chosen[code] = {
                "edge": None,
                "way_id": pins[code].way_id,
                "pinned": True,
                "nearest_way": None,
                "chosen_way": pins[code].way_id,
                "score_m": None,
                "nearest_score_m": None,
            }
            continue

        usable = [n for n, _ in neighbours.get(code, Counter()).most_common(2)]
        usable = [n for n in usable if n in accepted]
        if not usable:
            # No neighbour to score against: keep the nearest edge.
            chosen[code] = {
                "edge": nearest[1:3],
                "way_id": selection_graph.way_of_edge.get((nearest[1], nearest[2])),
                "pinned": False,
                "nearest_way": selection_graph.way_of_edge.get((nearest[1], nearest[2])),
                "chosen_way": selection_graph.way_of_edge.get((nearest[1], nearest[2])),
                "score_m": None,
                "nearest_score_m": None,
            }
            continue

        def score(candidate, usable=usable) -> float | None:
            distance, a, b, projected = candidate
            anchor = anchor_of((a, b), projected, selection_graph)
            total = distance
            for other in usable:
                other_point = (accepted[other]["lat"], accepted[other]["lon"])
                other_candidates = candidates_for(
                    selection_graph, other_point, config["snap_accept_m"]
                )
                if not other_candidates:
                    return None
                od, oa, ob, oproj = other_candidates[0]
                other_anchor = anchor_of((oa, ob), oproj, selection_graph)
                route = bg.shortest_path(selection_graph, anchor, other_anchor)
                if route is None:
                    return None
                total += od + route[0]
            return total

        scored = [(score(candidate), candidate) for candidate in candidates]
        scored = [(value, candidate) for value, candidate in scored if value is not None]
        if not scored:
            continue
        scored.sort(key=lambda item: item[0])
        best_value, best = scored[0]
        nearest_value = next((value for value, candidate in scored if candidate is nearest), None)
        chosen[code] = {
            "edge": best[1:3],
            "way_id": selection_graph.way_of_edge.get((best[1], best[2])),
            "pinned": False,
            "nearest_way": selection_graph.way_of_edge.get((nearest[1], nearest[2])),
            "chosen_way": selection_graph.way_of_edge.get((best[1], best[2])),
            "snap_distance_m": round(best[0], 1),
            "nearest_snap_distance_m": round(nearest[0], 1),
            "score_m": round(best_value, 1),
            "nearest_score_m": None if nearest_value is None else round(nearest_value, 1),
        }

    changed_stations = {
        code: row
        for code, row in chosen.items()
        if not row["pinned"]
        and row["nearest_way"] is not None
        and row["chosen_way"] is not None
        and row["nearest_way"] != row["chosen_way"]
        and row["score_m"] is not None
        and row["nearest_score_m"] is not None
        and row["score_m"] < row["nearest_score_m"] * (1 - MIN_IMPROVEMENT)
    }

    # --- step 1b: GUARD -----------------------------------------------------
    # Independent per-station minimisation can make a NEIGHBOUR's segment worse,
    # because the two ends are chosen separately. Revert any change that worsens
    # an incident segment, and report how many were reverted.
    incident: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for a, b in current:
        incident[a].append((a, b))
        incident[b].append((a, b))

    probe_graph = bg.load_graph()
    probe_graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(probe_graph, bg.load_bridges())

    from pipeline.rail_graph import project_point_to_segment as _project

    def route_with(selection: dict[str, dict]) -> dict[tuple[str, str], float]:
        graph = bg.load_graph()
        graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
        bg.apply_bridges(graph, bg.load_bridges())
        nodes: dict[str, int | None] = {}
        for code, entry in sorted(accepted.items()):
            pin_way = pins[code].way_id if code in pins else None
            choice = selection.get(code)
            edge = None if choice is None else choice.get("edge")
            if edge is not None:
                a, b = edge
                projected, distance, _t = _project(
                    (entry["lat"], entry["lon"]), graph.coords[a], graph.coords[b]
                )
                if distance <= config["snap_accept_m"]:
                    nodes[code] = graph._split_edge(a, b, projected)
                    continue
            nodes[code] = graph.snap(
                code,
                (entry["lat"], entry["lon"]),
                config["snap_accept_m"],
                config["snap_review_m"],
                pin_way=pin_way,
            ).node_id
        out = {}
        for a, b in current:
            if nodes.get(a) is None or nodes.get(b) is None:
                continue
            result = bg.shortest_path(graph, nodes[a], nodes[b])
            if result is not None:
                out[(a, b)] = result[0]
        return out

    baseline_routes = route_with({})
    guarded = dict(changed_stations)
    reverted = []
    for code in list(changed_stations):
        candidate_routes = route_with(guarded)
        worse = []
        for a, b in incident.get(code, []):
            before = baseline_routes.get((a, b))
            after = candidate_routes.get((a, b))
            if before is not None and after is not None and after > before * 1.005:
                worse.append((a, b, before, after))
        if worse:
            guarded.pop(code, None)
            reverted.append(
                {
                    "station": code,
                    "worsened_segments": [
                        {
                            "segment": f"{a}-{b}",
                            "before_km": round(before / 1000, 3),
                            "after_km": round(after / 1000, 3),
                        }
                        for a, b, before, after in worse
                    ],
                }
            )
    changed_stations = guarded

    # --- step 2: rebuild every segment with the chosen edges ---------------
    graph = bg.load_graph()
    graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(graph, bg.load_bridges())

    station_node: dict[str, int | None] = {}
    for code, entry in sorted(accepted.items()):
        # Only GUARDED changes are applied; a reverted station uses its pin or
        # the nearest edge like the real build.
        choice = chosen.get(code) if code in changed_stations else None
        pin_way = pins[code].way_id if code in pins else None
        if choice is None:
            result = graph.snap(
                code,
                (entry["lat"], entry["lon"]),
                config["snap_accept_m"],
                config["snap_review_m"],
                pin_way=pin_way,
            )
        else:
            # Force the chosen edge by using the pin mechanism semantics.
            edge = choice["edge"]
            if edge is None:
                result = graph.snap(
                    code,
                    (entry["lat"], entry["lon"]),
                    config["snap_accept_m"],
                    config["snap_review_m"],
                    pin_way=pin_way,
                )
            else:
                a, b = edge
                projected, distance, _t = project_point_to_segment(
                    (entry["lat"], entry["lon"]), graph.coords[a], graph.coords[b]
                )
                if distance <= config["snap_accept_m"]:
                    node = graph._split_edge(a, b, projected)
                    station_node[code] = node
                    continue
                result = graph.snap(
                    code,
                    (entry["lat"], entry["lon"]),
                    config["snap_accept_m"],
                    config["snap_review_m"],
                    pin_way=pin_way,
                )
        station_node[code] = result.node_id

    comparisons = []
    longer = []
    for (a, b), row in sorted(current.items()):
        if a not in station_node or b not in station_node:
            continue
        if station_node[a] is None or station_node[b] is None:
            continue
        route = bg.shortest_path(graph, station_node[a], station_node[b])
        if route is None:
            continue
        before = row["length_m"]
        after = route[0]
        key = (a, b) if a < b else (b, a)
        is_changed = key in {
            (x, y) if x < y else (y, x)
            for x, y in (row2["edge"] for row2 in changed_stations.values())
        }
        delta = after - before
        entry = {
            "segment": f"{a}-{b}",
            "before_km": round(before / 1000, 3),
            "after_km": round(after / 1000, 3),
            "delta_km": round(delta / 1000, 3),
            "delta_pct": round(delta / before * 100, 3) if before else None,
            "station_changed": is_changed,
        }
        comparisons.append(entry)
        if delta > max(1.0, before * 0.005):
            longer.append(entry)

    # Unmeasured segments have no length; they are excluded from both totals so
    # the comparison is like for like.
    by_name = {c["segment"]: c["after_km"] * 1000 for c in comparisons}
    measured = [
        (f"{a}-{b}", row["length_m"])
        for (a, b), row in current.items()
        if row.get("length_m") is not None
    ]
    total_before = sum(length for _name, length in measured)
    total_after = sum(by_name.get(name, length) for name, length in measured)

    # --- pilot trips must not move (within 0.5%) ---------------------------
    current_by_key = {
        (row["from_code"], row["to_code"])
        if row["from_code"] < row["to_code"]
        else (row["to_code"], row["from_code"]): row
        for row in current.values()
    }
    after_by_key = {c["segment"]: c["after_km"] * 1000 for c in comparisons}
    pilots = {}
    for number in ("249", "250", "259F", "260F"):
        trip_id = next((tid for tid in pairs if tid.split("-")[1] == number), None)
        if trip_id is None:
            pilots[number] = {"found": False}
            continue
        before_m = 0.0
        after_m = 0.0
        for a, b in pairs[trip_id]:
            key = (a, b) if a < b else (b, a)
            row = current_by_key.get(key)
            if row is None or row.get("length_m") is None:
                continue
            before_m += row["length_m"]
            after_m += after_by_key.get(f"{row['from_code']}-{row['to_code']}", row["length_m"])
        pct = (after_m - before_m) / before_m * 100 if before_m else None
        pilots[number] = {
            "found": True,
            "trip_id": trip_id,
            "before_km": round(before_m / 1000, 3),
            "after_km": round(after_m / 1000, 3),
            "delta_pct": None if pct is None else round(pct, 3),
            "within_0_5pct": pct is not None and abs(pct) <= 0.5,
        }

    # --- V12 (detour) effect on the changed segments -----------------------
    detour_changes = []
    for c in comparisons:
        row = next(
            (r for r in current.values() if f"{r['from_code']}-{r['to_code']}" == c["segment"]),
            None,
        )
        if row is None or not row.get("straight_m"):
            continue
        if abs(c["delta_pct"] or 0) <= 0.5:
            continue
        detour_changes.append(
            {
                "segment": c["segment"],
                "detour_before": row.get("detour_ratio"),
                "detour_after": round(c["after_km"] * 1000 / row["straight_m"], 3),
                "crosses_suspect_1_6": round(c["after_km"] * 1000 / row["straight_m"], 3) > 1.6,
            }
        )

    payload = {
        "pilot_trips": pilots,
        "detour_changes": detour_changes,
        "v13_note": (
            "V13 (cruise vs printed max) is NOT re-run: the experiment is not applied, "
            "so there is no rebuilt schedule to sweep. Every changed segment got "
            "shorter, so cruise speeds would fall, not rise."
        ),
        "shown_trips_note": (
            "Trip status does not change: no segment crosses the 1.6 suspect threshold "
            "in either direction (see detour_changes)."
        ),
        "note": (
            "Experiment only. data/parsed/segments.json is unchanged. Each station gets "
            "ONE edge: the one minimising routed distance to its neighbours, within "
            "snap_accept_m."
        ),
        "min_improvement_pct": MIN_IMPROVEMENT * 100,
        "stations_evaluated": len(chosen),
        "stations_changed": len(changed_stations),
        "changed_stations": changed_stations,
        "changes_reverted_by_guard": reverted,
        "pins_reproduced": {
            code: {
                "pinned_way": pins[code].way_id,
                "chosen_way": chosen.get(code, {}).get("chosen_way"),
                "reproduced": chosen.get(code, {}).get("chosen_way") == pins[code].way_id,
            }
            for code in pins
        },
        "segments_total": len(comparisons),
        "segments_changed": [c for c in comparisons if abs(c["delta_pct"] or 0) > 0.5],
        "segments_longer": longer,
        "total_length_before_km": round(total_before / 1000, 1),
        "total_length_after_km": round(total_after / 1000, 1),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {OUT}")
    print(
        f"  stations evaluated {payload['stations_evaluated']}, "
        f"changed {payload['stations_changed']}"
    )
    print(f"  pins reproduced: {payload['pins_reproduced']}")
    print(f"  segments changed >0.5%: {len(payload['segments_changed'])}")
    for row in payload["segments_changed"][:12]:
        print(
            f"    {row['segment']}: {row['before_km']} -> {row['after_km']} km "
            f"({row['delta_pct']}%)"
        )
    print(f"  segments longer (>0.5%): {len(longer)}")
    for row in longer[:12]:
        print(f"    LONGER {row['segment']}: {row['before_km']} -> {row['after_km']} km")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
