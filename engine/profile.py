"""Trapezoidal motion profile (Phase 5, ADR 004).

PURE: no I/O, no clock, no randomness.

Between two consecutive TIMED waypoints i -> j:

- ``D = T_j - T_i`` seconds, ``L = S_j - S_i`` metres;
- an end gets an acceleration/deceleration phase ONLY if that row is a ``stop``
  (a train at rest). A ``pass`` row gets none;
- ``a_s = min(accel_time_s, D/3)`` at an eased start, ``a_e`` likewise at an
  eased end;
- cruise speed ``v = L / (D - a_s/2 - a_e/2)``;
- the position is piecewise quadratic (accelerating), linear (cruising), then
  quadratic (decelerating), and reaches exactly ``S_j`` at ``T_j``.

This is an ASSUMPTION about how trains move, not something the Gapeka states.
The output always carries ``motion_model = "trapezoid_v1"``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Leg:
    """One timed leg between waypoint i and waypoint j."""

    t_i: float  # seconds (absolute, since service-date midnight)
    t_j: float
    s_i: float  # metres along the trip polyline
    s_j: float
    ease_start_s: float
    ease_end_s: float
    cruise_mps: float

    @property
    def duration(self) -> float:
        return self.t_j - self.t_i

    @property
    def length(self) -> float:
        return self.s_j - self.s_i


def build_leg(
    t_i: float,
    t_j: float,
    s_i: float,
    s_j: float,
    ease_start: bool,
    ease_end: bool,
    accel_time_s: float,
) -> Leg | None:
    """Build a leg, or None when it is degenerate (no time or no distance)."""
    duration = t_j - t_i
    length = s_j - s_i
    if duration <= 0 or length <= 0:
        return None

    # A leg may not spend more than a third of its time easing at each end.
    ease_s = 0.0 if not ease_start else min(accel_time_s, duration / 3.0)
    ease_e = 0.0 if not ease_end else min(accel_time_s, duration / 3.0)

    # Guard: the eased portions must leave a positive cruise interval.
    if ease_s + ease_e >= duration:
        scale = duration / (ease_s + ease_e + 1e-9) * 0.99
        ease_s *= scale
        ease_e *= scale

    cruise_time = duration - ease_s / 2.0 - ease_e / 2.0
    if cruise_time <= 0:
        return None
    return Leg(
        t_i=t_i,
        t_j=t_j,
        s_i=s_i,
        s_j=s_j,
        ease_start_s=ease_s,
        ease_end_s=ease_e,
        cruise_mps=length / cruise_time,
    )


def distance_at(leg: Leg, t: float) -> float:
    """Distance along the leg at absolute time ``t`` (clamped to the leg)."""
    if t <= leg.t_i:
        return leg.s_i
    if t >= leg.t_j:
        return leg.s_j

    v = leg.cruise_mps
    dt = t - leg.t_i
    duration = leg.duration
    a_s = leg.ease_start_s
    a_e = leg.ease_end_s

    if a_s > 0 and dt < a_s:
        # Quadratic acceleration from rest.
        accel = v / a_s
        return leg.s_i + 0.5 * accel * dt * dt

    cruise_start = a_s
    cruise_end = duration - a_e
    if dt <= cruise_end:
        return leg.s_i + 0.5 * v * a_s + v * (dt - cruise_start)

    # Quadratic deceleration to rest at s_j.
    remaining = leg.t_j - t
    decel = v / a_e if a_e > 0 else 0.0
    return leg.s_j - 0.5 * decel * remaining * remaining


def speed_at(leg: Leg, t: float) -> float:
    """Speed in m/s at absolute time ``t`` (0 at an eased end)."""
    if t <= leg.t_i or t >= leg.t_j:
        return 0.0
    v = leg.cruise_mps
    a_s = leg.ease_start_s
    a_e = leg.ease_end_s
    dt = t - leg.t_i
    remaining = leg.t_j - t

    if a_s > 0 and dt < a_s:
        return (v / a_s) * dt
    if a_e > 0 and remaining < a_e:
        return (v / a_e) * remaining
    return v
