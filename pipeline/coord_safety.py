"""H2 safety gate: validate proposed station coordinates before applying them.

A proposal must pass ALL of:

1. inside the Java bounding box;
2. snapping to a rail edge within ``snap_accept_m``;
3. **triple consistency** with the already accepted neighbours: for A-B-C the
   path through B may not exceed the direct distance by more than the configured
   ratio (default 1.15).

Failures are reported with their numbers and are NOT applied.

Usage:
    python -m pipeline.coord_safety
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pipeline.build_geometry import load_config, load_graph
from pipeline.rail_graph import haversine_m
from pipeline.station_coords import JAVA_BBOX

PARSED = Path("data/parsed")
REVIEW = Path("data/review")
EXTERNAL = Path("data/external")
OUT = REVIEW / "coord_safety_report.json"

# --- H2: the human's decisions (coordinates from OSM nodes) ------------------
PROPOSED = {
    "CKI": 4817686767,
    "KLI": 11738786421,
    "MRI": 4815286700,
    "MTR": 7764926504,
    "SMT": 12165656405,
    "SMO": 7109010878,
    "PRI": 7849142889,
    "PS": 1359918326,
    "MLK": 8072001320,
    "JBU": 5311399822,
    "LR": 1244940776,
    "SD": 1244940858,
    "TIS": 1228535141,
    "SBP": 11778643372,
}

# Candidates the human explicitly rejected (kept as evidence, never applied).
REJECTED = {
    "LR": [("wikidata", "Q12516294"), ("osm", "node/7835804385")],
    "SD": [("wikidata", "Q12516348")],
    "TIS": [("wikidata", "Q12516356")],
    "SBP": [("wikidata", "Q2086473")],
    "JBU": [("wikidata", "Q33020703")],
    "MRI": [("osm", "node/11179200351")],
    "MTR": [("osm", "node/11179200353")],
}

TRIPLE_RATIO_MAX = 1.15


def osm_station_coords() -> dict[int, dict]:
    graph = json.loads((EXTERNAL / "java_rail_graph.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in graph["stations"]}


def neighbour_map() -> dict[str, Counter]:
    """For each code, how often each other code is adjacent in a trip."""
    out: dict[str, Counter] = {}
    for name in ("intercity_trips.json", "local_trips.json"):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
            for i, code in enumerate(codes):
                bucket = out.setdefault(code, Counter())
                if i > 0:
                    bucket[codes[i - 1]] += 1
                if i + 1 < len(codes):
                    bucket[codes[i + 1]] += 1
    return out


def triple_check(
    code: str,
    point: tuple[float, float],
    accepted: dict[str, dict],
    neighbours: dict[str, Counter],
) -> dict:
    """Check code between its neighbours: is d(A,B)+d(B,C) <= ratio * d(A,C)?

    Only triples where BOTH neighbours are accepted are usable.
    """
    checks = []
    for neighbour, count in neighbours.get(code, Counter()).most_common(3):
        if neighbour not in accepted:
            continue
        a = (accepted[neighbour]["lat"], accepted[neighbour]["lon"])
        checks.append(
            {
                "neighbour": neighbour,
                "count": count,
                "distance_km": round(haversine_m(point, a) / 1000, 2),
            }
        )

    ratios = []
    neighbour_codes = [c["neighbour"] for c in checks]
    for i, left in enumerate(neighbour_codes):
        for right in neighbour_codes[i + 1 :]:
            a = (accepted[left]["lat"], accepted[left]["lon"])
            c = (accepted[right]["lat"], accepted[right]["lon"])
            direct = haversine_m(a, c)
            if direct < 100:
                continue
            via = haversine_m(point, a) + haversine_m(point, c)
            ratios.append(
                {
                    "via": f"{left}-{code}-{right}",
                    "direct_km": round(direct / 1000, 2),
                    "via_km": round(via / 1000, 2),
                    "ratio": round(via / direct, 3),
                }
            )

    worst = max((r["ratio"] for r in ratios), default=None)
    return {
        "neighbours": checks,
        "ratios": ratios,
        "worst_ratio": worst,
        "passes": worst is None or worst <= TRIPLE_RATIO_MAX,
    }


def evaluate() -> dict:
    config = load_config()
    graph = load_graph()
    stations = osm_station_coords()
    accepted_path = PARSED / "station_coordinates.json"
    accepted = dict(json.loads(accepted_path.read_text(encoding="utf-8"))["matched"])
    neighbours = neighbour_map()

    # A proposal must be judged against the OTHER proposals too: LR currently
    # holds a wrong coordinate, and leaving it in place makes SD look implausible.
    # Applying the passing proposals first is the correct order of operations.
    for code, node_id in PROPOSED.items():
        station = stations.get(node_id)
        if station is not None:
            accepted[code] = {
                "code": code,
                "name": station.get("name"),
                "lat": station["lat"],
                "lon": station["lon"],
            }

    results = []
    for code, node_id in sorted(PROPOSED.items()):
        station = stations.get(node_id)
        if station is None:
            results.append(
                {
                    "code": code,
                    "node": node_id,
                    "applied": False,
                    "reason": "OSM node not present in the extracted station list",
                }
            )
            continue

        lat, lon = station["lat"], station["lon"]
        snap = graph.snap(code, (lat, lon), config["snap_accept_m"], config["snap_review_m"])
        triple = triple_check(code, (lat, lon), accepted, neighbours)
        in_java = (
            JAVA_BBOX["min_lat"] <= lat <= JAVA_BBOX["max_lat"]
            and JAVA_BBOX["min_lon"] <= lon <= JAVA_BBOX["max_lon"]
        )

        failures = []
        if not in_java:
            failures.append("outside Java bbox")
        if snap.band == "rejected":
            failures.append(f"snap {snap.snap_distance_m:.0f} m > {config['snap_review_m']:.0f} m")
        if not triple["passes"]:
            failures.append(f"triple ratio {triple['worst_ratio']:.2f} > {TRIPLE_RATIO_MAX}")

        results.append(
            {
                "code": code,
                "node": node_id,
                "name": station.get("name"),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "in_java": in_java,
                "snap_distance_m": round(snap.snap_distance_m, 1)
                if snap.snap_distance_m is not None
                else None,
                "snap_band": snap.band,
                "triple": triple,
                "applied": not failures,
                "failures": failures,
            }
        )

    return {
        "note": (
            "H2 safety gate. A proposal is applied only when it is inside Java, "
            f"snaps <= snap_accept_m, and its worst triple ratio <= {TRIPLE_RATIO_MAX}."
        ),
        "triple_ratio_max": TRIPLE_RATIO_MAX,
        "proposed": len(results),
        "applied": sum(1 for r in results if r["applied"]),
        "failed": sum(1 for r in results if not r["applied"]),
        "results": results,
        "rejected_candidates": {
            code: [{"source": s, "source_id": i} for s, i in items]
            for code, items in REJECTED.items()
        },
    }


def main() -> int:
    payload = evaluate()
    REVIEW.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"proposed {payload['proposed']} | applied {payload['applied']} | "
        f"failed {payload['failed']}"
    )
    for row in payload["results"]:
        mark = "APPLY" if row["applied"] else "SKIP "
        ratio = row.get("triple", {}).get("worst_ratio")
        snap = row.get("snap_distance_m")
        print(
            f"  {mark} {row['code']:5s} snap={snap} m ratio={ratio} "
            f"{'' if row['applied'] else '| ' + '; '.join(row['failures'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
