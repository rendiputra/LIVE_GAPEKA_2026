"""Snapshot loader (Phase 5).

The ONLY module in the engine that touches SQLite. It reads the database once,
builds immutable structures, and verifies the version row and the geometry
content hash so a stale or mismatched database cannot be estimated silently.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.model import (
    DEFAULT_TZ,
    SegmentGeom,
    Snapshot,
    Trip,
    Waypoint,
)
from pipeline.rail_graph import haversine_m

DEFAULT_DB = Path("data/gapeka.db")
DEFAULT_SEGMENTS = Path("data/parsed/segments.json")

VISIBLE_STATUSES = ("complete", "complete_estimated", "has_fallback")


def _sod(value: str | None) -> int | None:
    """'08:40:00' -> seconds of day."""
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def _segment_geometries(segments_path: Path) -> dict[tuple[str, str], dict]:
    payload = json.loads(segments_path.read_text(encoding="utf-8"))
    return {(s["from_code"], s["to_code"]): s for s in payload["segments"]}


def _oriented(segment: dict, from_code: str) -> list[tuple[float, float]]:
    coords = (segment.get("geometry") or {}).get("coordinates") or []
    points = [(c[1], c[0]) for c in coords]
    if segment["from_code"] != from_code:
        points.reverse()
    return points


def _cumulative(points: list[tuple[float, float]]) -> tuple[float, ...]:
    out = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        out.append(out[-1] + haversine_m(a, b))
    return tuple(out)


def load(
    db_path: Path = DEFAULT_DB,
    segments_path: Path = DEFAULT_SEGMENTS,
    expected_hash: str | None = None,
) -> Snapshot:
    """Build an immutable snapshot from the database.

    Raises ``ValueError`` when the version row is missing or the geometry hash
    does not match, rather than estimating from inconsistent data.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        version = connection.execute(
            "SELECT id, name, effective_from, effective_to, pdf_sha256, status FROM gapeka_versions"
        ).fetchone()
        if version is None:
            raise ValueError("gapeka_versions is empty")

        statuses = {
            row[0]: {"status": row[1], "has_bypassed": bool(row[2])}
            for row in connection.execute(
                "SELECT trip_id, status, has_bypassed_waypoints FROM trip_geometry_status"
            )
        }
        bypass = {
            (row[0], row[1])
            for row in connection.execute("SELECT trip_id, seq FROM trip_waypoint_estimates")
        }

        segments = _segment_geometries(segments_path)
        geometry_hash = json.loads(segments_path.read_text(encoding="utf-8")).get("content_hash")
        if expected_hash and geometry_hash != expected_hash:
            raise ValueError(f"geometry content hash mismatch: {geometry_hash} != {expected_hash}")

        trips: list[Trip] = []
        max_day_offset = 0

        rows = connection.execute(
            "SELECT trip_id, train_no, book, service_class, service_class_source,"
            " completeness, has_untimed_markers, relation, origin, destination"
            " FROM trips ORDER BY trip_id"
        ).fetchall()

        for (
            trip_id,
            train_no,
            book,
            service_class,
            class_source,
            _completeness,
            has_markers,
            _relation,
            _origin,
            _destination,
        ) in rows:
            meta = statuses.get(trip_id)
            if meta is None or meta["status"] not in VISIBLE_STATUSES:
                continue
            status = meta["status"]
            has_bypass = meta["has_bypassed"]

            stop_rows = connection.execute(
                "SELECT seq, station_code, arrive, depart, day_offset, stop_type,"
                " time_source, arrive_day_offset, depart_day_offset"
                " FROM stop_times WHERE trip_id = ? ORDER BY seq",
                (trip_id,),
            ).fetchall()
            if len(stop_rows) < 2:
                continue

            # Build oriented segment list along the trip, honouring bypasses.
            bypassed_seqs = {seq for (tid, seq) in bypass if tid == trip_id}

            waypoints: list[Waypoint] = []
            segment_list: list[SegmentGeom] = []
            cumulative = 0.0
            previous_index: int | None = None

            for index, row in enumerate(stop_rows):
                (
                    seq,
                    code,
                    arrive,
                    depart,
                    day_offset,
                    stop_type,
                    time_source,
                    arrive_day_offset,
                    depart_day_offset,
                ) = row
                max_day_offset = max(max_day_offset, int(day_offset or 0))
                is_bypassed = seq in bypassed_seqs

                if previous_index is not None and not is_bypassed:
                    prev = stop_rows[previous_index]
                    key = (prev[1], code)
                    segment = segments.get(key) or segments.get((code, prev[1]))
                    if segment and segment.get("length_m"):
                        points = _oriented(segment, prev[1])
                        if points:
                            cum = _cumulative(points)
                            segment_list.append(
                                SegmentGeom(
                                    from_code=prev[1],
                                    to_code=code,
                                    length_m=float(segment["length_m"]),
                                    quality=segment["quality"],
                                    coordinates=tuple(points),
                                    cumulative_m=cum,
                                )
                            )
                            cumulative += float(segment["length_m"])

                if is_bypassed:
                    continue

                timed = bool(arrive or depart)
                arrive_sod = _sod(arrive)
                depart_sod = _sod(depart)
                # First row: arrive = depart. Last row: depart = arrive.
                if arrive_sod is None and depart_sod is not None and index == 0:
                    arrive_sod = depart_sod
                if depart_sod is None and arrive_sod is not None and index == len(stop_rows) - 1:
                    depart_sod = arrive_sod
                if stop_type == "pass" and arrive_sod is None:
                    arrive_sod = depart_sod

                waypoints.append(
                    Waypoint(
                        seq=seq,
                        station_code=code,
                        stop_type=stop_type,
                        arrive_sod=arrive_sod,
                        depart_sod=depart_sod,
                        day_offset=int(day_offset or 0),
                        arrive_day_offset=int(arrive_day_offset or 0),
                        depart_day_offset=int(depart_day_offset or 0),
                        s_m=cumulative,
                        timed=timed,
                        bypassed=False,
                    )
                )
                previous_index = index

            timed_points = [
                w for w in waypoints if w.arrive_abs is not None and w.depart_abs is not None
            ]
            if len(timed_points) < 2:
                continue

            first_abs = timed_points[0].depart_abs
            last_abs = timed_points[-1].arrive_abs
            if first_abs is None or last_abs is None:
                continue

            trips.append(
                Trip(
                    trip_id=trip_id,
                    train_no=train_no,
                    name=None,
                    book=int(book),
                    service_class=service_class,
                    calendar_source=class_source or "unknown",
                    geometry_status=status,
                    has_untimed_markers=bool(has_markers),
                    has_bypassed_waypoints=bool(has_bypass),
                    has_straight_line_segment=any(
                        s.quality == "straight_line" for s in segment_list
                    ),
                    waypoints=tuple(waypoints),
                    segments=tuple(segment_list),
                    first_abs=int(first_abs),
                    last_abs=int(last_abs),
                    total_length_m=cumulative,
                )
            )
    finally:
        connection.close()

    return Snapshot(
        version_id=int(version[0]),
        version_name=version[1],
        effective_from=version[2],
        effective_to=version[3],
        content_hash=geometry_hash or "",
        trips=tuple(trips),
        max_day_offset=max_day_offset,
        station_tz=DEFAULT_TZ,
    )
