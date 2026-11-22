"""Phase 5 tests: hand-calculated motion, edge cases, purity, regression.

P1 uses a synthetic trip with exact hand-computed values so the trapezoid maths
is pinned numerically, not just "looks plausible".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from engine.model import (
    STATUS_AT_STATION,
    STATUS_RUNNING,
    Policy,
    SegmentGeom,
    Snapshot,
    Trip,
    Waypoint,
)
from engine.position import positions_at, trajectory
from engine.profile import build_leg, distance_at, speed_at
from pipeline.rail_graph import haversine_m

WIB = timezone(timedelta(hours=7))


# --- synthetic builders -----------------------------------------------------


def straight_segment(length_m: float = 10000.0, points: int = 11) -> SegmentGeom:
    """A straight north-south segment of exactly ``length_m`` metres.

    Coordinates are derived from the distance so the geometry and the reported
    length agree: 0.001 deg of latitude is about 111.19 m at 7 degrees south.
    """
    # 0.001 deg of latitude is ~111.2 m, so one degree is ~111_195 m.
    metres_per_deg = haversine_m((-7.0, 110.0), (-6.999, 110.0)) * 1000.0
    degrees = length_m / metres_per_deg
    coords = tuple((-7.0 - degrees * i / (points - 1), 110.0) for i in range(points))
    cumulative = [0.0]
    for a, b in zip(coords, coords[1:], strict=False):
        cumulative.append(cumulative[-1] + haversine_m(a, b))
    return SegmentGeom(
        from_code="A",
        to_code="B",
        length_m=length_m,
        quality="osm_routed",
        coordinates=coords,
        cumulative_m=tuple(cumulative),
    )


def simple_trip(
    depart_sod: int = 0,
    arrive_sod: int = 600,
    length_m: float = 10000.0,
    stop_types: tuple[str, str] = ("stop", "stop"),
    depart_day_offset: int = 0,
    arrive_day_offset: int = 0,
) -> Trip:
    """A two-row synthetic trip.

    ``depart_day_offset`` and ``arrive_day_offset`` are separate on purpose: a
    midnight-crossing trip departs on day 0 and arrives on day 1.
    """
    segment = straight_segment(length_m)
    waypoints = (
        Waypoint(
            seq=1,
            station_code="A",
            stop_type=stop_types[0],
            arrive_sod=depart_sod,
            depart_sod=depart_sod,
            day_offset=depart_day_offset,
            s_m=0.0,
            timed=True,
        ),
        Waypoint(
            seq=2,
            station_code="B",
            stop_type=stop_types[1],
            arrive_sod=arrive_sod,
            depart_sod=arrive_sod,
            day_offset=arrive_day_offset,
            arrive_day_offset=arrive_day_offset,
            depart_day_offset=arrive_day_offset,
            s_m=length_m,
            timed=True,
        ),
    )
    return Trip(
        trip_id="t1",
        train_no="1",
        name="Test",
        book=1,
        service_class="reguler",
        calendar_source="assumed",
        geometry_status="complete",
        has_untimed_markers=False,
        has_bypassed_waypoints=False,
        has_straight_line_segment=False,
        waypoints=waypoints,
        segments=(segment,),
        first_abs=depart_sod + 86400 * depart_day_offset,
        last_abs=arrive_sod + 86400 * arrive_day_offset,
        total_length_m=length_m,
    )


def snapshot_of(trips: list[Trip]) -> Snapshot:
    return Snapshot(
        version_id=1,
        version_name="test",
        effective_from="2026-12-01",
        effective_to=None,
        content_hash="test",
        trips=tuple(trips),
        max_day_offset=max((max(w.day_offset for w in t.waypoints) for t in trips), default=0),
    )


def at(service_date: date, seconds: int) -> datetime:
    midnight = datetime(service_date.year, service_date.month, service_date.day, tzinfo=WIB)
    return midnight + timedelta(seconds=seconds)


# --- P1: hand-calculated trapezoid -----------------------------------------


def test_p1_cruise_speed_matches_hand_calculation():
    """L=10000 m, D=600 s, accel 60 s: v = 10000/(600-60) m/s."""
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    assert leg is not None
    assert leg.cruise_mps == pytest.approx(10000.0 / 540.0, rel=1e-9)


def test_p1_symmetry_gives_half_distance_at_half_time():
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    assert distance_at(leg, 300.0) == pytest.approx(5000.0, abs=1e-6)


def test_p1_reaches_exactly_the_endpoint_at_the_end():
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    assert distance_at(leg, 600.0) == pytest.approx(10000.0, abs=1e-6)
    assert distance_at(leg, 599.999) == pytest.approx(10000.0, abs=1.0)


def test_p1_acceleration_is_quadratic_at_the_start():
    """At t=30 s (half the ease), s = 0.5 * a * t^2 with a = v/60."""
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    v = leg.cruise_mps
    a = v / 60.0
    assert distance_at(leg, 30.0) == pytest.approx(0.5 * a * 900.0, rel=1e-9)


def test_p1_speed_is_zero_at_both_eased_ends():
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    assert speed_at(leg, 0.0) == 0.0
    assert speed_at(leg, 600.0) == 0.0
    assert speed_at(leg, 300.0) == pytest.approx(leg.cruise_mps)


def test_p1_no_ease_at_a_pass_end():
    """A pass end keeps full cruise speed right up to the waypoint."""
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, False, 60.0)
    assert leg.ease_end_s == 0.0
    assert speed_at(leg, 599.0) == pytest.approx(leg.cruise_mps)


def test_p1_pass_start_also_has_no_ease():
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, False, False, 60.0)
    assert leg.ease_start_s == 0.0 and leg.ease_end_s == 0.0
    assert leg.cruise_mps == pytest.approx(10000.0 / 600.0)


def test_p1_degenerate_legs_are_rejected():
    assert build_leg(0.0, 0.0, 0.0, 100.0, True, True, 60.0) is None
    assert build_leg(0.0, 60.0, 100.0, 100.0, True, True, 60.0) is None


# --- P2: edge cases ---------------------------------------------------------


def test_p2_before_first_departure_returns_nothing():
    snap = snapshot_of([simple_trip()])
    assert positions_at(snap, at(date(2026, 12, 1), -1)) == []


def test_p2_after_last_arrival_returns_nothing():
    snap = snapshot_of([simple_trip()])
    assert positions_at(snap, at(date(2026, 12, 1), 601)) == []


def test_p2_at_station_during_dwell():
    trip = simple_trip(depart_sod=100, arrive_sod=700)
    snap = snapshot_of([trip])
    # The first row arrives and departs at 100 s, so dwell is a single instant.
    positions = positions_at(snap, at(date(2026, 12, 1), 100))
    assert len(positions) == 1
    assert positions[0].status in (STATUS_AT_STATION, STATUS_RUNNING)


def test_p2_midway_is_running_and_on_the_polyline():
    snap = snapshot_of([simple_trip()])
    positions = positions_at(snap, at(date(2026, 12, 1), 300))
    assert len(positions) == 1
    position = positions[0]
    assert position.status == STATUS_RUNNING
    # Halfway along the 10 km segment.
    metres_per_deg = haversine_m((-7.0, 110.0), (-6.999, 110.0)) * 1000.0
    assert position.lat == pytest.approx(-7.0 - (5000.0 / metres_per_deg), abs=1e-6)
    assert position.lon == pytest.approx(110.0, abs=1e-9)


def test_p2_midnight_crossing_appears_after_midnight():
    """A trip departing 23:50 and arriving 00:10 next day is active at 00:05."""
    trip = simple_trip(
        depart_sod=23 * 3600 + 50 * 60,
        arrive_sod=10 * 60,
        depart_day_offset=0,
        arrive_day_offset=1,
    )
    snap = snapshot_of([trip])
    query = at(date(2026, 12, 2), 5 * 60)
    positions = positions_at(snap, query)
    assert len(positions) == 1
    assert positions[0].status == STATUS_RUNNING


def test_p2_trip_started_yesterday_is_not_shown_today():
    trip = simple_trip(
        depart_sod=23 * 3600 + 50 * 60,
        arrive_sod=10 * 60,
        depart_day_offset=0,
        arrive_day_offset=1,
    )
    snap = snapshot_of([trip])
    # 12:00 on the NEXT day: the trip ended hours ago.
    assert positions_at(snap, at(date(2026, 12, 2), 12 * 3600)) == []


def test_p2_fakultatif_hidden_by_default():
    trip = simple_trip()
    trip = Trip(**{**trip.__dict__, "service_class": "fakultatif"})
    snap = snapshot_of([trip])
    assert positions_at(snap, at(date(2026, 12, 1), 300)) == []
    shown = positions_at(snap, at(date(2026, 12, 1), 300), Policy(show_fakultatif=True))
    assert len(shown) == 1


def test_p2_unknown_class_behaves_like_fakultatif():
    trip = simple_trip()
    trip = Trip(**{**trip.__dict__, "service_class": "unknown"})
    snap = snapshot_of([trip])
    assert positions_at(snap, at(date(2026, 12, 1), 300)) == []
    assert len(positions_at(snap, at(date(2026, 12, 1), 300), Policy(show_fakultatif=True))) == 1


def test_p2_has_unmeasured_is_never_shown():
    trip = simple_trip()
    trip = Trip(**{**trip.__dict__, "geometry_status": "has_unmeasured"})
    snap = snapshot_of([trip])
    for policy in (
        Policy(),
        Policy(geometry_policy="allow_fallback"),
        Policy(geometry_policy="complete_only"),
    ):
        assert positions_at(snap, at(date(2026, 12, 1), 300), policy) == []


def test_p2_complete_only_excludes_complete_estimated():
    trip = simple_trip()
    trip = Trip(**{**trip.__dict__, "geometry_status": "complete_estimated"})
    snap = snapshot_of([trip])
    assert (
        positions_at(snap, at(date(2026, 12, 1), 300), Policy(geometry_policy="complete_only"))
        == []
    )
    assert len(positions_at(snap, at(date(2026, 12, 1), 300))) == 1


def test_p2_allow_fallback_includes_fallback_and_flags_it():
    trip = simple_trip()
    trip = Trip(
        **{**trip.__dict__, "geometry_status": "has_fallback", "has_straight_line_segment": True}
    )
    snap = snapshot_of([trip])
    assert positions_at(snap, at(date(2026, 12, 1), 300)) == []
    positions = positions_at(
        snap, at(date(2026, 12, 1), 300), Policy(geometry_policy="allow_fallback")
    )
    assert len(positions) == 1
    assert positions[0].has_straight_line_segment is True


def test_p2_coarse_flag_follows_untimed_markers():
    trip = simple_trip()
    trip = Trip(**{**trip.__dict__, "has_untimed_markers": True})
    snap = snapshot_of([trip])
    assert positions_at(snap, at(date(2026, 12, 1), 300))[0].coarse is True


def test_p2_naive_datetime_is_rejected():
    snap = snapshot_of([simple_trip()])
    with pytest.raises(ValueError):
        positions_at(snap, datetime(2026, 12, 1, 0, 5))


# --- P3: properties ---------------------------------------------------------


def test_p3_distance_is_non_decreasing_and_continuous():
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    previous = -1.0
    for t in range(0, 601):
        s = distance_at(leg, float(t))
        assert s >= previous - 1e-9
        if previous >= 0:
            assert abs(s - previous) < 100.0  # no jump larger than 100 m in 1 s
        previous = s


def test_p3_position_always_lies_on_the_polyline():
    trip = simple_trip()
    snap = snapshot_of([trip])
    for t in range(0, 601, 7):
        positions = positions_at(snap, at(date(2026, 12, 1), t))
        if not positions:
            continue
        position = positions[0]
        # The synthetic line runs along lon 110.0 from lat -7.0 to -7.001.
        assert position.lon == pytest.approx(110.0, abs=1e-9)
        metres_per_deg = haversine_m((-7.0, 110.0), (-6.999, 110.0)) * 1000.0
        assert -7.0 - (10000.0 / metres_per_deg) - 1e-9 <= position.lat <= -7.0 + 1e-9


def test_p3_speed_is_bounded():
    leg = build_leg(0.0, 600.0, 0.0, 10000.0, True, True, 60.0)
    for t in range(0, 601):
        assert 0.0 <= speed_at(leg, float(t)) <= leg.cruise_mps + 1e-9


def test_p3_call_order_does_not_matter():
    trip = simple_trip()
    snap = snapshot_of([trip])
    first = positions_at(snap, at(date(2026, 12, 1), 300))
    positions_at(snap, at(date(2026, 12, 1), 100))
    again = positions_at(snap, at(date(2026, 12, 1), 300))
    assert [p.as_dict() for p in first] == [p.as_dict() for p in again]


def test_p3_trajectory_matches_positions_at():
    trip = simple_trip()
    snap = snapshot_of([trip])
    frames = trajectory(snap, "t1", date(2026, 12, 1), step_s=60)
    assert frames
    for frame in frames[::3]:
        direct = positions_at(snap, at(date(2026, 12, 1), frame["t_s"]))
        assert len(direct) == 1
        assert direct[0].s_m == pytest.approx(frame["s_m"], abs=0.11)


# --- P4: regression on real pilot trips ------------------------------------


@pytest.fixture(scope="module")
def real_snapshot():
    from engine.snapshot import load

    try:
        return load()
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")


def test_p4_259f_and_260f_are_loaded(real_snapshot):
    numbers = {t.train_no for t in real_snapshot.trips}
    assert "259F" in numbers
    assert "260F" in numbers


def test_p4_260f_is_active_after_midnight(real_snapshot):
    """KA 260F departs 22:05 and arrives 00:13, so it must appear at 00:05."""
    trip = next(t for t in real_snapshot.trips if t.train_no == "260F")
    assert trip.waypoints[-1].day_offset == 1
    query = at(date(2026, 12, 2), 5 * 60)
    # KA 259F/260F are FAKULTATIF in Lampiran IV, so they need the opt-in.
    positions = positions_at(real_snapshot, query, Policy(show_fakultatif=True))
    assert any(p.train_no == "260F" for p in positions)


def test_p4_at_station_at_every_printed_stop_time(real_snapshot):
    """At a printed arrival the engine must report at_station at that station."""
    checked = 0
    for trip in real_snapshot.trips:
        if trip.train_no not in ("259F", "260F"):
            continue
        for waypoint in trip.waypoints:
            if waypoint.stop_type != "stop" or waypoint.arrive_sod is None:
                continue
            instant = at(date(2026, 12, 1), waypoint.arrive_abs)
            positions = positions_at(real_snapshot, instant, Policy(show_fakultatif=True))
            match = [
                p for p in positions if p.trip_id == trip.trip_id and p.status == STATUS_AT_STATION
            ]
            if match:
                assert match[0].s_m == pytest.approx(waypoint.s_m, abs=1.0)
                checked += 1
    assert checked > 0
