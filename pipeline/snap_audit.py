"""T3: audit every station's snap distance.

F3: KDB had an accepted Wikidata coordinate 5,208 m from rail that went unnoticed
until H11. This audit makes that class of problem visible for EVERY station, so a
future coordinate cannot fail silently.

Report only; nothing is changed.

Usage:
    python -m pipeline.snap_audit
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/gapeka.db")
SNAPS = Path("data/review/geometry_snaps.json")
OUT = Path("data/review/snap_audit.json")

WARN_M = 100.0
ACCEPT_M = 100.0


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def audit() -> dict:
    snaps = json.loads(SNAPS.read_text(encoding="utf-8")) if SNAPS.exists() else {}

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        stations = {
            row[0]: {
                "code": row[0],
                "name": row[1],
                "official_name": row[2],
                "coord_status": row[3],
                "coord_provenance": row[4],
                "lat": row[5],
                "lon": row[6],
                "coord_source": row[7],
                "coord_source_id": row[8],
            }
            for row in connection.execute(
                "SELECT code, name, official_name, coord_status, coord_provenance,"
                " lat, lon, coord_source, coord_source_id FROM stations"
            )
        }
    finally:
        connection.close()

    rows = []
    for code, station in sorted(stations.items()):
        snap = snaps.get(code) or {}
        distance = snap.get("snap_distance_m")
        rows.append(
            {
                **station,
                "snap_distance_m": None if distance is None else round(distance, 1),
                "band": snap.get("band", "no_coordinate" if station["lat"] is None else "unknown"),
                "node_id": snap.get("node_id"),
            }
        )

    measured = [row["snap_distance_m"] for row in rows if row["snap_distance_m"] is not None]
    routable = [row for row in rows if row["coord_status"] in ("accepted", "override")]

    over_threshold = [
        row
        for row in routable
        if row["snap_distance_m"] is not None and row["snap_distance_m"] > WARN_M
    ]
    over_threshold.sort(key=lambda row: -(row["snap_distance_m"] or 0))

    rejected = [row for row in rows if row["coord_status"] == "rejected"]
    missing = [row for row in rows if row["coord_status"] == "missing"]

    return {
        "note": (
            "T3 snap audit. 'accepted' and 'override' coordinates are the ones that "
            "reach geometry; anything above 100 m is listed explicitly. Report only."
        ),
        "warn_threshold_m": WARN_M,
        "stations_total": len(rows),
        "routable_total": len(routable),
        "distribution_m": {
            "max": round(max(measured), 1) if measured else None,
            "p99": round(percentile(measured, 0.99), 1) if measured else None,
            "p95": round(percentile(measured, 0.95), 1) if measured else None,
            "median": round(percentile(measured, 0.50), 1) if measured else None,
        },
        "over_100m": over_threshold,
        "rejected": rejected,
        "missing": missing,
        "rows": rows,
    }


def main() -> int:
    payload = audit()
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  stations {payload['stations_total']}, routable {payload['routable_total']}")
    print(f"  distribution {payload['distribution_m']}")
    print(f"  over {WARN_M:.0f} m: {len(payload['over_100m'])}")
    for row in payload["over_100m"]:
        print(
            f"    {row['code']:5s} {row['snap_distance_m']:8.1f} m  {row['coord_status']:9s}"
            f" {row['coord_source']} {row['coord_source_id']}"
        )
    print(f"  rejected {len(payload['rejected'])}, missing {len(payload['missing'])}")
    for row in payload["rejected"]:
        print(f"    REJECTED {row['code']} {row['snap_distance_m']} m")
    for row in payload["missing"]:
        print(f"    MISSING  {row['code']} {row['official_name'] or row['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
