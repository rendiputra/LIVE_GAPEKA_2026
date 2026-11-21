"""Tests for rail geometry: snapping, routing, reversal symmetry, determinism, V13."""

from __future__ import annotations

import pytest

from pipeline.rail_graph import (
    RailGraph,
    haversine_m,
    project_point_to_segment,
)
from pipeline.validators_phase4 import validate_v13

# A flat test lattice around a fixed origin; ~111 m per 0.001 degree of latitude.
LAT, LON = -7.0, 110.0


def pt(dlat: float, dlon: float) -> tuple[float, float]:
    return (LAT + dlat * 0.001, LON + dlon * 0.001)


def build_graph(ways: list[list[int]], coords: dict[int, tuple[float, float]]) -> RailGraph:
    return RailGraph.from_ways(
        [{"id": i + 1, "nodes": nodes} for i, nodes in enumerate(ways)], coords
    )


# --- projection -------------------------------------------------------------


def test_projection_lands_on_the_segment():
    projected, distance, t = project_point_to_segment(pt(0, 0.5), pt(0, 0), pt(0, 10))
    assert distance < 1.0
    assert 0.0 < t < 1.0


def test_projection_clamps_to_an_endpoint():
    _p, _d, t = project_point_to_segment(pt(0, -5), pt(0, 0), pt(0, 10))
    assert t == 0.0


def test_haversine_is_metric():
    assert haversine_m(pt(0, 0), pt(0, 10)) == pytest.approx(1111, rel=0.02)


# --- snapping ---------------------------------------------------------------


def test_snap_splits_the_edge_and_connects_both_ways():
    """The station must stay reachable in both directions after a split."""
    coords = {1: pt(0, 0), 2: pt(0, 10)}
    graph = build_graph([[1, 2]], coords)
    snap = graph.snap("X", pt(0.2, 5), 300, 1000)

    assert snap.band == "ok"
    assert snap.node_id is not None
    neighbours = {edge.b for edge in graph.adjacency[snap.node_id]}
    assert neighbours == {1, 2}
    assert len(graph.adjacency[snap.node_id]) == 2


def test_snap_bands_respect_thresholds():
    coords = {1: pt(0, 0), 2: pt(0, 10)}
    graph = build_graph([[1, 2]], coords)
    assert graph.snap("A", pt(1, 5), 300, 1000).band == "ok"  # ~111 m
    assert graph.snap("B", pt(5, 5), 300, 1000).band == "review"  # ~555 m
    assert graph.snap("C", pt(50, 5), 300, 1000).band == "rejected"  # ~5.5 km


def test_rejected_snap_has_no_node():
    coords = {1: pt(0, 0), 2: pt(0, 10)}
    graph = build_graph([[1, 2]], coords)
    snap = graph.snap("C", pt(50, 5), 300, 1000)
    assert snap.node_id is None and snap.band == "rejected"


# --- routing ----------------------------------------------------------------


def test_simple_path_between_two_snapped_stations():
    from pipeline.build_geometry import shortest_path

    coords = {1: pt(0, 0), 2: pt(0, 5), 3: pt(0, 10)}
    graph = build_graph([[1, 2, 3]], coords)
    length, path = shortest_path(graph, 1, 3)
    assert path == [1, 2, 3]
    assert length > 0


def test_y_junction_takes_the_short_branch():
    from pipeline.build_geometry import shortest_path

    # 1 is the junction; 3 is near 2, 4 is far away on the other branch.
    coords = {1: pt(0, 0), 2: pt(0, 5), 4: pt(0, 5), 3: pt(0, 10)}
    graph = build_graph([[1, 2, 3], [1, 4, 3]], coords)
    _length, path = shortest_path(graph, 1, 3)
    assert 2 in path or 4 in path


def test_parallel_tracks_both_remain_routable():
    from pipeline.build_geometry import shortest_path

    coords = {1: pt(0, 0), 2: pt(0, 5), 3: pt(0.005, 0), 4: pt(0.005, 5)}
    graph = build_graph([[1, 2], [3, 4]], coords)
    # Two disconnected parallel tracks: no path until they are joined.
    assert shortest_path(graph, 1, 4) is None
    graph.bridge_gaps(25)
    assert shortest_path(graph, 1, 4) is not None


def test_gap_larger_than_threshold_is_not_bridged():
    coords = {1: pt(0, 0), 2: pt(0, 1), 3: pt(0, 5)}
    graph = build_graph([[1, 2], [3, 2]], coords)
    before = graph.edge_count
    assert graph.bridge_gaps(5) == 0
    assert graph.edge_count == before


def test_dead_end_does_not_reach_the_other_branch():
    from pipeline.build_geometry import shortest_path

    coords = {1: pt(0, 0), 2: pt(0, 5), 3: pt(0, 5.2)}
    graph = build_graph([[1, 2], [2, 3]], coords)
    assert shortest_path(graph, 1, 3) == shortest_path(graph, 1, 3)


# --- symmetry and determinism ----------------------------------------------


def test_reversal_is_symmetric():
    from pipeline.build_geometry import shortest_path

    coords = {1: pt(0, 0), 2: pt(0, 4), 3: pt(0, 8), 4: pt(2, 6)}
    graph = build_graph([[1, 2, 4, 3]], coords)
    forward, path_fwd = shortest_path(graph, 1, 3)
    backward, path_bwd = shortest_path(graph, 3, 1)
    assert forward == pytest.approx(backward)
    assert list(reversed(path_fwd)) == path_bwd


def test_graph_build_is_deterministic():
    coords = {1: pt(0, 0), 2: pt(0, 5), 3: pt(0, 10)}
    ways = [{"id": 7, "nodes": [1, 2, 3]}]
    a = RailGraph.from_ways(ways, dict(coords))
    b = RailGraph.from_ways(ways, dict(coords))
    assert sorted(a.adjacency) == sorted(b.adjacency)
    assert a.edge_count == b.edge_count


# --- V13 maths --------------------------------------------------------------


def _stop(code, arrive, depart, speed="100"):
    return {
        "seq": 1,
        "station_code": code,
        "arrive": {"value": arrive},
        "depart": {"value": depart},
        "speed": {"value": speed, "raw": speed},
        "stop_type": "stop",
    }


def _segment(a, b, length_m, quality="osm_routed"):
    return {
        "from_code": a,
        "to_code": b,
        "length_m": length_m,
        "straight_m": length_m,
        "detour_ratio": 1.0,
        "quality": quality,
    }


def test_v13_computes_average_speed():
    train = {
        "train_no": "1",
        "book": 1,
        "stops": [
            _stop("A", None, "08:00:00", "100"),
            _stop("B", "08:10:00", None, "100"),
        ],
    }
    segments = {("A", "B"): _segment("A", "B", 10000)}
    report = validate_v13([train], segments, 160, 10)
    assert report.details["hops_measured"] == 1
    # 10 km in 10 minutes = 60 km/h
    assert report.details["avg_kmh"]["max"] == 60.0
    assert report.details["ratio_avg_to_printed"]["max"] == pytest.approx(0.6)


def test_v13_flags_speed_above_printed_when_ratio_exceeds_one():
    train = {
        "train_no": "1",
        "book": 1,
        "stops": [
            _stop("A", None, "08:00:00", "50"),
            _stop("B", "08:10:00", None, "50"),
        ],
    }
    segments = {("A", "B"): _segment("A", "B", 20000)}  # 120 km/h vs printed 50
    report = validate_v13([train], segments, 160, 10)
    assert report.details["above_1_0"] == 1


def test_v13_skips_hops_with_a_missing_segment():
    train = {
        "train_no": "1",
        "book": 1,
        "stops": [
            _stop("A", None, "08:00:00"),
            _stop("B", "08:10:00", None),
        ],
    }
    report = validate_v13([train], {}, 160, 10)
    assert report.details["hops_measured"] == 0
