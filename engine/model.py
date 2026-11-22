"""Immutable engine data model (Phase 5).

Everything here is a plain dataclass: no I/O, no clock, no randomness. The
snapshot loader builds these once; the pure functions in ``profile`` and
``position`` only read them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- motion / policy defaults ------------------------------------------------
MOTION_MODEL = "trapezoid_v1"
DEFAULT_TZ = "Asia/Jakarta"  # WIB; every Java station is WIB

STATUS_AT_STATION = "at_station"
STATUS_RUNNING = "running"

POLICY_COMPLETE_AND_ESTIMATED = "complete_and_estimated"
POLICY_COMPLETE_ONLY = "complete_only"
POLICY_ALLOW_FALLBACK = "allow_fallback"


@dataclass(frozen=True)
class Policy:
    """Explicit, immutable query policy. Nothing is hidden or defaulted silently."""

    calendar_policy: str = "regular_daily_assumed"
    show_fakultatif: bool = False
    enforce_effective_from: bool = False
    geometry_policy: str = POLICY_COMPLETE_AND_ESTIMATED
    accel_time_s: float = 60.0
    origin_lead_s: float = 0.0
    terminal_linger_s: float = 0.0
    max_day_offset: int = 2

    def as_dict(self) -> dict:
        return {
            "calendar_policy": self.calendar_policy,
            "show_fakultatif": self.show_fakultatif,
            "enforce_effective_from": self.enforce_effective_from,
            "geometry_policy": self.geometry_policy,
            "accel_time_s": self.accel_time_s,
            "origin_lead_s": self.origin_lead_s,
            "terminal_linger_s": self.terminal_linger_s,
            "max_day_offset": self.max_day_offset,
        }


@dataclass(frozen=True)
class Waypoint:
    """One row of a trip with a distance along the trip polyline."""

    seq: int
    station_code: str
    stop_type: str
    arrive_sod: int | None  # seconds from the start of the SERVICE DATE
    depart_sod: int | None
    day_offset: int  # DEPRECATED alias for depart_day_offset
    s_m: float  # cumulative distance along the trip polyline
    timed: bool  # False for distance-only markers
    arrive_day_offset: int = 0
    depart_day_offset: int = 0
    bypassed: bool = False

    @property
    def arrive_abs(self) -> int | None:
        if self.arrive_sod is None:
            return None
        # Q3: the arrival may be on the previous day when the stop straddles
        # midnight (e.g. arrive 23:58, depart 00:03).
        return self.arrive_sod + 86400 * self.arrive_day_offset

    @property
    def depart_abs(self) -> int | None:
        if self.depart_sod is None:
            return None
        return self.depart_sod + 86400 * self.depart_day_offset


@dataclass(frozen=True)
class SegmentGeom:
    """A routed segment with cumulative distances for fast point lookup."""

    from_code: str
    to_code: str
    length_m: float
    quality: str
    coordinates: tuple[tuple[float, float], ...]  # (lat, lon) oriented from->to
    cumulative_m: tuple[float, ...]

    def point_at(self, distance_m: float) -> tuple[float, float]:
        """Interpolate a (lat, lon) at ``distance_m`` along the segment."""
        import bisect

        if not self.coordinates:
            raise ValueError("segment has no geometry")
        if distance_m <= 0:
            return self.coordinates[0]

        # Clamp against the POLYLINE length, not the reported length_m: the two
        # can differ by rounding, and clamping only on length_m let the index run
        # past the end of the array.
        polyline_length = self.cumulative_m[-1]
        if distance_m >= polyline_length:
            return self.coordinates[-1]

        index = bisect.bisect_left(self.cumulative_m, distance_m)
        if index <= 0:
            return self.coordinates[0]
        if index >= len(self.coordinates):
            return self.coordinates[-1]
        before = self.cumulative_m[index - 1]
        after = self.cumulative_m[index]
        span = after - before
        if span <= 0:
            return self.coordinates[index]
        ratio = (distance_m - before) / span
        lat0, lon0 = self.coordinates[index - 1]
        lat1, lon1 = self.coordinates[index]
        return (lat0 + (lat1 - lat0) * ratio, lon0 + (lon1 - lon0) * ratio)


@dataclass(frozen=True)
class Trip:
    """A trip ready for position estimation."""

    trip_id: str
    train_no: str
    name: str | None
    book: int
    service_class: str
    calendar_source: str
    geometry_status: str
    has_untimed_markers: bool
    has_bypassed_waypoints: bool
    has_straight_line_segment: bool
    waypoints: tuple[Waypoint, ...]
    segments: tuple[SegmentGeom, ...]
    first_abs: int
    last_abs: int
    total_length_m: float
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def service_days(self) -> str:
        """Which days the trip is assumed to run (ADR 002)."""
        if self.calendar_source == "assumed" and self.service_class == "reguler":
            return "daily_assumed"
        return "unknown"

    def is_visible(self, policy: Policy) -> bool:
        """E7: which geometry statuses may be shown."""
        if self.geometry_status == "has_unmeasured":
            return False
        if policy.geometry_policy == POLICY_ALLOW_FALLBACK:
            return True
        if policy.geometry_policy == POLICY_COMPLETE_ONLY:
            return self.geometry_status == "complete"
        return self.geometry_status in ("complete", "complete_estimated")


@dataclass(frozen=True)
class Snapshot:
    """Everything the pure functions need."""

    version_id: int
    version_name: str
    effective_from: str
    effective_to: str | None
    content_hash: str
    trips: tuple[Trip, ...]
    max_day_offset: int
    station_tz: str = DEFAULT_TZ

    def as_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "version_name": self.version_name,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "content_hash": self.content_hash,
            "trips": len(self.trips),
            "max_day_offset": self.max_day_offset,
            "station_tz": self.station_tz,
        }


@dataclass(frozen=True)
class TrainPosition:
    """One train's estimated position at an instant."""

    trip_id: str
    train_no: str
    name: str | None
    lat: float
    lon: float
    bearing: float
    status: str
    s_m: float
    from_code: str
    to_code: str
    next_stop_code: str | None
    next_stop_time: str | None
    speed_kmh: float
    estimated: bool
    coarse: bool
    has_bypassed_waypoints: bool
    has_straight_line_segment: bool
    service_class: str
    calendar_source: str

    def as_dict(self) -> dict:
        return {
            "trip_id": self.trip_id,
            "train_no": self.train_no,
            "name": self.name,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "bearing": round(self.bearing, 1),
            "status": self.status,
            "s_m": round(self.s_m, 1),
            "from_code": self.from_code,
            "to_code": self.to_code,
            "next_stop_code": self.next_stop_code,
            "next_stop_time": self.next_stop_time,
            "speed_kmh": round(self.speed_kmh, 1),
            "estimated": True,
            "coarse": self.coarse,
            "has_bypassed_waypoints": self.has_bypassed_waypoints,
            "has_straight_line_segment": self.has_straight_line_segment,
            "service_class": self.service_class,
            "calendar_source": self.calendar_source,
            "motion_model": MOTION_MODEL,
        }
