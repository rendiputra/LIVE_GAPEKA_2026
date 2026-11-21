"""H3: record everything known about station LRA (Larangan, Kab. Brebes).

Report only. Nothing is changed. Every figure in a chat summary about H3 must
come from ``data/review/h3_lra.json``, so this script exists to produce it
instead of relying on hand arithmetic.

Usage:
    python -m pipeline.h3_lra
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from pipeline import build_geometry as bg
from pipeline.rail_graph import haversine_m
from pipeline.triple_rail import RATIO_LIMIT, turn_angle

OUT = Path("data/review/h3_lra.json")
DB = Path("data/gapeka.db")
CODE = "LRA"
OSM_CANDIDATE_NODE = 7835804385


def main() -> int:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT code, name, official_name, coord_status, lat, lon,"
            " coord_source, coord_source_id, coord_match, coord_confidence,"
            " coord_retrieved FROM stations WHERE code = ?",
            (CODE,),
        ).fetchone()
        if row is None:
            print(f"{CODE} not found in stations")
            return 2

        # Trips that use LRA, and the station's neighbours in those trips.
        trips_with: list[str] = []
        neighbours: Counter[str] = Counter()
        rows = connection.execute(
            "SELECT trip_id, seq, station_code, stop_type FROM stop_times ORDER BY trip_id, seq"
        ).fetchall()
        by_trip: dict[str, list[tuple[int, str, str]]] = {}
        for trip_id, seq, code, stop_type in rows:
            by_trip.setdefault(trip_id, []).append((seq, code, stop_type))

        for trip_id, stops in by_trip.items():
            codes = [code for _, code, _ in stops]
            if CODE not in codes:
                continue
            trips_with.append(trip_id)
            index = codes.index(CODE)
            if index > 0:
                neighbours[codes[index - 1]] += 1
            if index + 1 < len(codes):
                neighbours[codes[index + 1]] += 1
    finally:
        connection.close()

    accepted = bg.accepted_coordinates()
    entry = accepted.get(CODE)
    point = (row[4], row[5]) if row[4] is not None else None

    # Compare with the OSM station node that might be LRA.
    graph_file = Path("data/external/java_rail_graph.json")
    osm_match = None
    if graph_file.exists():
        payload = json.loads(graph_file.read_text(encoding="utf-8"))
        for station in payload.get("stations", []):
            if station.get("id") == OSM_CANDIDATE_NODE:
                distance = None
                if point is not None:
                    distance = round(haversine_m(point, (station["lat"], station["lon"])), 1)
                osm_match = {
                    "node_id": OSM_CANDIDATE_NODE,
                    "name": station.get("name"),
                    "railway": station.get("railway"),
                    "lat": station["lat"],
                    "lon": station["lon"],
                    "distance_from_accepted_m": distance,
                }
                break

    # Rail-path triple test for LRA against its two most common neighbours.
    config = bg.load_config()
    graph = bg.load_graph()
    graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(graph, bg.load_bridges())

    snaps = {
        code: graph.snap(
            code,
            (data["lat"], data["lon"]),
            config["snap_accept_m"],
            config["snap_review_m"],
        )
        for code, data in accepted.items()
    }

    def rail_distance(a: str, b: str) -> float | None:
        sa, sb = snaps.get(a), snaps.get(b)
        if not sa or not sb or sa.node_id is None or sb.node_id is None:
            return None
        result = bg.shortest_path(graph, sa.node_id, sb.node_id)
        return result[0] if result else None

    triple = None
    top = [code for code, _ in neighbours.most_common(2)]
    if len(top) == 2 and all(code in accepted for code in top):
        a, c = top
        direct = rail_distance(a, c)
        via = (rail_distance(a, CODE), rail_distance(CODE, c))
        if direct and None not in via and direct > 0:
            ratio = (via[0] + via[1]) / direct
            triple = {
                "via": f"{a}-{CODE}-{c}",
                "ratio": round(ratio, 3),
                "ratio_limit": RATIO_LIMIT,
                "passes": ratio <= RATIO_LIMIT,
                "turn_angle_deg": round(
                    turn_angle(
                        (accepted[a]["lat"], accepted[a]["lon"]),
                        point,
                        (accepted[c]["lat"], accepted[c]["lon"]),
                    ),
                    1,
                ),
                "rail_direct_km": round(direct / 1000, 2),
                "rail_via_km": round((via[0] + via[1]) / 1000, 2),
            }

    # Does the rail-path test report LRA anywhere?
    q3_path = Path("data/review/q3_triple_rail.json")
    q3_mention = None
    if q3_path.exists():
        q3 = json.loads(q3_path.read_text(encoding="utf-8"))
        q3_mention = {
            "in_failures": any(r["code"] == CODE for r in q3.get("failures", [])),
            "in_turnbacks": any(r["code"] == CODE for r in q3.get("junction_turnbacks", [])),
        }

    payload = {
        "note": (
            "H3: report only, nothing applied. LRA is a distinct station from LR. "
            "Every figure quoted about LRA must come from this file."
        ),
        "station": {
            "code": row[0],
            "name": row[1],
            "official_name": row[2],
            "coord_status": row[3],
            "lat": row[4],
            "lon": row[5],
            "coord_source": row[6],
            "coord_source_id": row[7],
            "coord_match": row[8],
            "coord_confidence": row[9],
            "coord_retrieved": row[10],
            "in_accepted_coordinates": entry is not None,
        },
        "osm_candidate": osm_match,
        "usage": {
            "trips": len(trips_with),
            "trip_ids_sample": sorted(trips_with)[:10],
            "neighbours": dict(neighbours.most_common()),
        },
        "rail_path_triple": triple,
        "q3_mention": q3_mention,
        "lr_for_contrast": None,
    }

    # LR for contrast, so "LRA is not LR" is evidenced, not asserted.
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        lr = connection.execute(
            "SELECT code, name, official_name, coord_status, lat, lon,"
            " coord_source, coord_source_id FROM stations WHERE code = 'LR'"
        ).fetchone()
    finally:
        connection.close()
    if lr:
        payload["lr_for_contrast"] = {
            "code": lr[0],
            "name": lr[1],
            "official_name": lr[2],
            "coord_status": lr[3],
            "lat": lr[4],
            "lon": lr[5],
            "coord_source": lr[6],
            "coord_source_id": lr[7],
        }
        if lr[4] is not None and point is not None:
            payload["lr_for_contrast"]["distance_from_lra_km"] = round(
                haversine_m(point, (lr[4], lr[5])) / 1000, 2
            )

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps(payload, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
