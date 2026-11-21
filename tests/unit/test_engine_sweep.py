"""Tests for the R1 sweep's continuity detector.

"0 continuity violations" is only meaningful if the detector actually detects
violations and does not silently skip legitimate resets. These tests pin both
directions.
"""

from __future__ import annotations

from types import SimpleNamespace

from pipeline.engine_sweep import continuity_step


def pos(trip_id: str, s_m: float) -> SimpleNamespace:
    return SimpleNamespace(trip_id=trip_id, s_m=s_m)


def test_forward_motion_is_not_a_violation():
    previous: dict[str, tuple[float, int]] = {}
    found, ambiguous = continuity_step(previous, {"t1": [pos("t1", 100.0)]}, 0)
    assert found == [] and ambiguous == 0

    found, ambiguous = continuity_step(previous, {"t1": [pos("t1", 400.0)]}, 60)
    assert found == [] and ambiguous == 0


def test_decreasing_distance_is_a_violation():
    previous: dict[str, tuple[float, int]] = {}
    continuity_step(previous, {"t1": [pos("t1", 5000.0)]}, 0)
    found, _ = continuity_step(previous, {"t1": [pos("t1", 10.0)]}, 60)
    assert len(found) == 1
    assert found[0]["reason"] == "distance decreased"
    assert found[0]["from_m"] == 5000.0
    assert found[0]["to_m"] == 10.0


def test_implausible_jump_is_a_violation():
    previous: dict[str, tuple[float, int]] = {}
    continuity_step(previous, {"t1": [pos("t1", 0.0)]}, 0)
    # 50 km in 60 s is far beyond the 120 m/s bound.
    found, _ = continuity_step(previous, {"t1": [pos("t1", 50000.0)]}, 60)
    assert len(found) == 1
    assert found[0]["reason"] == "implausible jump between samples"


def test_absent_then_reappearing_trip_is_a_new_run_not_a_violation():
    """A trip that vanishes and comes back at s_m=0 is a new service date."""
    previous: dict[str, tuple[float, int]] = {}
    continuity_step(previous, {"t1": [pos("t1", 347495.7)]}, 0)
    # Absent at t=60: the tracker must be dropped.
    found, _ = continuity_step(previous, {}, 60)
    assert found == []
    assert "t1" not in previous

    # Reappears at the start of a new run.
    found, _ = continuity_step(previous, {"t1": [pos("t1", 0.0)]}, 120)
    assert found == []


def test_two_runs_of_one_trip_at_one_instant_are_ambiguous_and_skipped():
    """Yesterday's run plus today's run: no comparison is possible, so none is made."""
    previous: dict[str, tuple[float, int]] = {}
    continuity_step(previous, {"t1": [pos("t1", 8000.0)]}, 0)
    found, ambiguous = continuity_step(previous, {"t1": [pos("t1", 87000.0), pos("t1", 50.0)]}, 60)
    assert found == []
    assert ambiguous == 1
    # The tracker is reset, so the next single sample cannot produce a false jump.
    found, _ = continuity_step(previous, {"t1": [pos("t1", 120.0)]}, 120)
    assert found == []
