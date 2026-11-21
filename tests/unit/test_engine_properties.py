"""P3: property tests for the motion profile and the pure position function."""

from __future__ import annotations

from datetime import timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.profile import build_leg, distance_at, speed_at

WIB = timezone(timedelta(hours=7))


@settings(max_examples=60, deadline=None)
@given(
    length_m=st.floats(min_value=50.0, max_value=200_000.0),
    duration_s=st.floats(min_value=30.0, max_value=20_000.0),
    accel_s=st.floats(min_value=0.0, max_value=300.0),
    ease_start=st.booleans(),
    ease_end=st.booleans(),
)
def test_distance_is_monotonic_and_bounded(length_m, duration_s, accel_s, ease_start, ease_end):
    leg = build_leg(0.0, duration_s, 0.0, length_m, ease_start, ease_end, accel_s)
    if leg is None:
        return

    previous = -1.0
    samples = 40
    for i in range(samples + 1):
        t = duration_s * i / samples
        s = distance_at(leg, t)
        assert -1e-6 <= s <= length_m + 1e-6
        assert s >= previous - 1e-6, "distance must never decrease"
        previous = s


@settings(max_examples=60, deadline=None)
@given(
    length_m=st.floats(min_value=50.0, max_value=200_000.0),
    duration_s=st.floats(min_value=30.0, max_value=20_000.0),
    accel_s=st.floats(min_value=0.0, max_value=300.0),
)
def test_speed_is_never_negative_and_bounded_by_cruise(length_m, duration_s, accel_s):
    leg = build_leg(0.0, duration_s, 0.0, length_m, True, True, accel_s)
    if leg is None:
        return
    for i in range(41):
        t = duration_s * i / 40
        v = speed_at(leg, t)
        assert v >= -1e-9
        assert v <= leg.cruise_mps + 1e-6


@settings(max_examples=40, deadline=None)
@given(
    length_m=st.floats(min_value=100.0, max_value=50_000.0),
    duration_s=st.floats(min_value=60.0, max_value=5_000.0),
)
def test_endpoints_are_exact(length_m, duration_s):
    leg = build_leg(0.0, duration_s, 0.0, length_m, True, True, 60.0)
    if leg is None:
        return
    assert distance_at(leg, 0.0) == 0.0
    assert distance_at(leg, duration_s) == length_m
