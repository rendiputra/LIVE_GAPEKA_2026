"""Pure position estimation (Phase 5).

PURE by contract: input is a snapshot, an aware datetime and an explicit policy.
No database, no network, no system clock, no randomness.

Time model (E2): every Java station is WIB. Schedule times are seconds from the
start of the SERVICE DATE, plus 86400 * day_offset. For a query instant we look
at service dates date(t_local) - k for k in 0..max_day_offset, so a trip that
started "yesterday" still appears after midnight (e.g. KA 260F).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from engine.model import (
    MOTION_MODEL,
    STATUS_AT_STATION,
    STATUS_RUNNING,
    Policy,
    SegmentGeom,
    Snapshot,
    TrainPosition,
    Trip,
    Waypoint,
)
from engine.profile import Leg, build_leg, distance_at, speed_at

WIB = ZoneInfo("Asia/Jakarta")
UTC = UTC


def _local(instant: datetime) -> datetime:
    if instant.tzinfo is None:
        raise ValueError("positions_at requires an aware datetime")
    return instant.astimezone(WIB)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _point_on_trip(trip: Trip, s_m: float) -> tuple[float, float]:
    """(lat, lon) at distance ``s_m`` along the trip's oriented polyline."""
    if not trip.segments:
        raise ValueError(f"trip {trip.trip_id} has no geometry")

    offset = 0.0
    for segment in trip.segments:
        if s_m <= offset + segment.length_m or segment is trip.segments[-1]:
            return segment.point_at(max(0.0, min(segment.length_m, s_m - offset)))
        offset += segment.length_m
    return trip.segments[-1].coordinates[-1]


def _segment_at(trip: Trip, s_m: float) -> SegmentGeom:
    offset = 0.0
    for segment in trip.segments:
        if s_m <= offset + segment.length_m or segment is trip.segments[-1]:
            return segment
        offset += segment.length_m
    return trip.segments[-1]


def _bearing_at(trip: Trip, s_m: float) -> float:
    segment = _segment_at(trip, s_m)
    point = segment.point_at(0.0)
    # A short step forward gives a stable tangent without extra state.
    ahead = segment.point_at(min(segment.length_m, 25.0))
    if ahead == point and len(segment.coordinates) > 1:
        return _bearing(segment.coordinates[0], segment.coordinates[1])
    return _bearing(point, ahead)


def _timed_waypoints(trip: Trip) -> list[tuple[int, Waypoint, int]]:
    """Waypoints with a usable departure/arrival, as (abs_time, waypoint, kind)."""
    out = []
    for waypoint in trip.waypoints:
        if waypoint.depart_abs is not None:
            out.append((waypoint.depart_abs, waypoint, 0))
    return out


def _legs(trip: Trip, policy: Policy) -> list[tuple[Leg, Waypoint, Waypoint]]:
    """Build all timed legs for a trip once (cached by the caller)."""
    timed = [w for w in trip.waypoints if w.arrive_abs is not None and w.depart_abs is not None]
    legs = []
    for a, b in zip(timed, timed[1:], strict=False):
        leg = build_leg(
            t_i=float(a.depart_abs),
            t_j=float(b.arrive_abs),
            s_i=a.s_m,
            s_j=b.s_m,
            ease_start=a.stop_type == "stop",
            ease_end=b.stop_type == "stop",
            accel_time_s=policy.accel_time_s,
        )
        if leg is not None:
            legs.append((leg, a, b))
    return legs


def _next_stop(trip: Trip, s_m: float) -> tuple[str | None, str | None]:
    """The next STOP row at or beyond the current distance, and its printed time."""
    for waypoint in trip.waypoints:
        if waypoint.s_m >= s_m - 1e-6 and waypoint.stop_type == "stop":
            printed = (
                waypoint.arrive_sod if waypoint.arrive_sod is not None else waypoint.depart_sod
            )
            text = None
            if printed is not None:
                h, rem = divmod(int(printed), 3600)
                m, s = divmod(rem, 60)
                text = f"{h:02d}:{m:02d}:{s:02d}"
            return waypoint.station_code, text
    return None, None


def _active_service_dates(local: datetime, policy: Policy, max_day_offset: int):
    today = local.date()
    for k in range(0, max_day_offset + 1):
        yield today - timedelta(days=k)


def _visible(trip: Trip, policy: Policy) -> bool:
    if not trip.is_visible(policy):
        return False
    # fakultatif AND unknown classes are hidden unless explicitly shown (E3).
    return policy.show_fakultatif or trip.service_class == "reguler"


def positions_at(
    snapshot: Snapshot,
    instant: datetime,
    policy: Policy | None = None,
) -> list[TrainPosition]:
    """Estimated positions of every visible, active trip at ``instant``."""
    policy = policy or Policy()
    local = _local(instant)
    out: list[TrainPosition] = []

    for service_date in _active_service_dates(local, policy, snapshot.max_day_offset):
        midnight = datetime(service_date.year, service_date.month, service_date.day, tzinfo=WIB)
        elapsed = (local - midnight).total_seconds()

        for trip in snapshot.trips:
            if not _visible(trip, policy):
                continue
            if not (trip.first_abs <= elapsed <= trip.last_abs):
                continue

            legs = _legs(trip, policy)
            if not legs:
                continue

            position = _position_for(trip, legs, elapsed, policy)
            if position is not None:
                out.append(position)
    return out


def _position_for(
    trip: Trip, legs: list[tuple[Leg, Waypoint, Waypoint]], elapsed: float, policy: Policy
) -> TrainPosition | None:
    # Dwell at a station, or running along a leg.
    for leg, a, b in legs:
        if (
            a.depart_abs is not None
            and a.arrive_abs is not None
            and a.arrive_abs <= elapsed < a.depart_abs
        ):
            return _make(trip, a.s_m, STATUS_AT_STATION, 0.0, a, b)
        if leg.t_i <= elapsed <= leg.t_j:
            if elapsed <= leg.t_i:
                return _make(trip, leg.s_i, STATUS_AT_STATION, 0.0, a, b)
            if elapsed >= leg.t_j:
                return _make(trip, leg.s_j, STATUS_AT_STATION, 0.0, a, b)
            s = distance_at(leg, elapsed)
            v = speed_at(leg, elapsed)
            return _make(trip, s, STATUS_RUNNING, v, a, b)

    last = legs[-1]
    if last[0].t_j <= elapsed <= last[0].t_j + policy.terminal_linger_s:
        return _make(trip, last[0].s_j, STATUS_AT_STATION, 0.0, last[1], last[2])
    return None


def _make(
    trip: Trip,
    s_m: float,
    status: str,
    speed_mps: float,
    a: Waypoint,
    b: Waypoint,
) -> TrainPosition:
    lat, lon = _point_on_trip(trip, s_m)
    next_code, next_time = _next_stop(trip, s_m)
    return TrainPosition(
        trip_id=trip.trip_id,
        train_no=trip.train_no,
        name=trip.name,
        lat=lat,
        lon=lon,
        bearing=_bearing_at(trip, s_m),
        status=status,
        s_m=s_m,
        from_code=a.station_code,
        to_code=b.station_code,
        next_stop_code=next_code,
        next_stop_time=next_time,
        speed_kmh=speed_mps * 3.6,
        estimated=True,
        coarse=trip.has_untimed_markers,
        has_bypassed_waypoints=trip.has_bypassed_waypoints,
        has_straight_line_segment=trip.has_straight_line_segment,
        service_class=trip.service_class,
        calendar_source=trip.calendar_source,
    )


def trajectory(
    snapshot: Snapshot,
    trip_id: str,
    service_date: date,
    policy: Policy | None = None,
    step_s: int = 60,
) -> list[dict]:
    """Sample one trip through a service date at ``step_s`` seconds."""
    policy = policy or Policy()
    trip = next((t for t in snapshot.trips if t.trip_id == trip_id), None)
    if trip is None:
        return []

    midnight = datetime(service_date.year, service_date.month, service_date.day, tzinfo=WIB)
    legs = _legs(trip, policy)
    if not legs:
        return []

    frames = []
    elapsed = trip.first_abs
    while elapsed <= trip.last_abs:
        position = _position_for(trip, legs, float(elapsed), policy)
        if position is not None:
            frames.append(
                {
                    "t_s": elapsed,
                    "time": (midnight + timedelta(seconds=elapsed)).isoformat(),
                    **position.as_dict(),
                    "motion_model": MOTION_MODEL,
                }
            )
        elapsed += step_s
    return frames
