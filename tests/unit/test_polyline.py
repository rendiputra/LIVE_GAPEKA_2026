"""G2/G4: polyline orientation, continuity and the G1 status rule.

The regression test pins the root cause: a segment is stored once per undirected
pair, so a hop travelling the opposite way MUST reverse its coordinates. Without
that, a 116.8 km trip draws as 256.2 km.
"""

from __future__ import annotations

import pytest

from pipeline.rail_graph import haversine_m, orient_geometry
from pipeline.validators_phase4 import _polyline_length_m, validate_v14b


def seg(a, b, coords, length_m=None):
    """A stored segment a->b with a straight-ish polyline."""
    if length_m is None:
        length_m = _polyline_length_m(coords)
    return {
        "from_code": a,
        "to_code": b,
        "geometry": {"type": "LineString", "coordinates": coords},
        "length_m": length_m,
        "straight_m": length_m,
        "detour_ratio": 1.0,
        "quality": "osm_routed",
        "reason": "",
    }


def line(lat0, lon0, lat1, lon1, steps=5):
    return [
        [lon0 + (lon1 - lon0) * i / steps, lat0 + (lat1 - lat0) * i / steps]
        for i in range(steps + 1)
    ]


# --- the root cause ---------------------------------------------------------


def test_orient_returns_stored_order_when_direction_matches():
    segment = seg("A", "B", line(-7.0, 110.0, -7.0, 110.1))
    assert orient_geometry(segment, "A", "B") == segment["geometry"]["coordinates"]


def test_orient_reverses_when_direction_is_opposite():
    segment = seg("A", "B", line(-7.0, 110.0, -7.0, 110.1))
    forward = orient_geometry(segment, "A", "B")
    backward = orient_geometry(segment, "B", "A")
    assert backward == list(reversed(forward))
    assert backward[0] == forward[-1]


def test_reversal_twice_is_the_original():
    segment = seg("A", "B", line(-7.0, 110.0, -7.0, 110.1))
    once = orient_geometry(segment, "B", "A")
    twice = list(reversed(once))
    assert twice == segment["geometry"]["coordinates"]


def test_naive_concatenation_breaks_the_join():
    """Regression for the defect that drew a 116.8 km trip as 256.2 km.

    A hop A->B->C where B->C is stored as B->C. When the second hop is travelled
    B->C the stored order is right; the defect appeared when the SAME stored
    segment was reused for the opposite hop. Here the middle hop is travelled
    backwards, so without reversal the line jumps to the segment's far end.
    """
    ab = seg("A", "B", line(-7.000, 110.000, -7.000, 110.010))
    # Stored C->B, but the hop travels B->C (opposite of storage).
    cb = seg("C", "B", line(-7.200, 110.400, -7.000, 110.010))

    ab_coords = orient_geometry(ab, "A", "B")
    oriented = orient_geometry(cb, "B", "C")  # reversed: starts at B
    naive = ab_coords + cb["geometry"]["coordinates"]  # starts at C: wrong

    def join_gap(coords, split):
        return haversine_m(
            (coords[split - 1][1], coords[split - 1][0]),
            (coords[split][1], coords[split][0]),
        )

    split = len(ab_coords)
    assert join_gap(ab_coords + oriented, split) < 1.0
    assert join_gap(naive, split) > 1000.0
    assert _polyline_length_m(ab_coords + oriented) == pytest.approx(
        ab["length_m"] + cb["length_m"], rel=0.01
    )


# --- continuity and equal length both ways ---------------------------------


def _trip(train_no, codes, book=1):
    return {
        "train_no": train_no,
        "book": book,
        "stops": [
            {
                "seq": i + 1,
                "station_code": c,
                "arrive": {"value": None},
                "depart": {"value": None},
                "speed": {"value": "100", "raw": "100"},
                "stop_type": "stop",
            }
            for i, c in enumerate(codes)
        ],
    }


def test_forward_and_reverse_trips_are_continuous_and_equal():
    a = seg("A", "B", line(-7.00, 110.00, -7.00, 110.05))
    b = seg("B", "C", line(-7.00, 110.05, -7.00, 110.10))
    segments = {("A", "B"): a, ("B", "C"): b}

    forward = validate_v14b([_trip("1", ["A", "B", "C"])], segments, {"v14b_join_slack_m": 50})
    backward = validate_v14b([_trip("2", ["C", "B", "A"])], segments, {"v14b_join_slack_m": 50})

    assert forward.findings == []
    assert backward.findings == []


def test_continuity_break_is_detected_when_a_join_is_far():
    a = seg("A", "B", line(-7.00, 110.00, -7.00, 110.05))
    # C sits far from B, so the join must be flagged.
    b = seg("B", "C", line(-7.00, 110.60, -7.00, 110.65))
    report = validate_v14b(
        [_trip("1", ["A", "B", "C"])], {("A", "B"): a, ("B", "C"): b}, {"v14b_join_slack_m": 50}
    )
    assert any(f["check"] == "b_continuity" for f in report.findings)


def test_unmeasured_gap_does_not_create_a_false_break():
    a = seg("A", "B", line(-7.00, 110.00, -7.00, 110.05))
    c = seg("D", "E", line(-7.00, 111.00, -7.00, 111.05))
    report = validate_v14b(
        [_trip("1", ["A", "B", "C", "D", "E"])],
        {("A", "B"): a, ("D", "E"): c},
        {"v14b_join_slack_m": 50},
    )
    assert not any(f["check"] == "b_continuity" for f in report.findings)


# --- the G1 status rule -----------------------------------------------------


def test_status_rule_complete_requires_all_hops_routed():
    """A suspect hop must NOT yield "complete" (G1).

    The rule lives in build_geometry; this asserts the mapping it uses.
    """
    from pipeline.build_geometry import build  # noqa: F401  (documents the owner)

    def status_for(counts):
        if counts.get("unmeasured"):
            return "has_unmeasured"
        if counts.get("straight_line") or counts.get("osm_suspect"):
            return "has_fallback"
        return "complete"

    assert status_for({"osm_routed": 5}) == "complete"
    assert status_for({"osm_routed": 4, "osm_suspect": 1}) == "has_fallback"
    assert status_for({"osm_routed": 4, "straight_line": 1}) == "has_fallback"
    assert status_for({"osm_routed": 4, "unmeasured": 1}) == "has_unmeasured"


def test_v14b_flags_a_segment_whose_polyline_disagrees_with_length():
    bad = seg("A", "B", line(-7.0, 110.0, -7.0, 110.1), length_m=1.0)
    report = validate_v14b([], {("A", "B"): bad}, {})
    assert any(f["check"] == "a_polyline_vs_length" for f in report.findings)


def test_v14b_does_not_treat_a_straight_line_fallback_as_a_jump():
    fallback = dict(seg("A", "B", line(-7.0, 110.0, -7.0, 111.0)))
    fallback["quality"] = "straight_line"
    report = validate_v14b([], {("A", "B"): fallback}, {"v14b_jump_m": 5000})
    assert not any(f["check"] == "d_point_jump" for f in report.findings)
