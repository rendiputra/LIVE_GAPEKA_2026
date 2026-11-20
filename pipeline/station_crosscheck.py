"""S1 — independent cross-check of every station coordinate match.

Four independent signals, none of which can alone confirm a match:

a) **Wikidata vs OSM agreement** — distance between the two sources' candidates.
b) **Name similarity** — Gapeka printed name vs the matched source label.
   A match by code alone is never "high" confidence.
c) **Neighbour consistency** — for consecutive triples A-B-C, how much longer the
   path through B is than the direct A-C distance.
d) **Duplicate proximity** — two different codes closer than 50 m.

Output: ``data/review/stations_crosscheck.json``. No correction is applied.
"""

from __future__ import annotations

import difflib
import json
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.cross_checks import haversine_km
from pipeline.station_coords import (
    normalise_name,
    osm_candidates,
    wikidata_by_code,
)
from pipeline.station_overrides import load as load_overrides

PARSED = Path("data/parsed")
EXTERNAL = Path("data/external")
REVIEW = Path("data/review")
CONFIG = Path("data/config/stations.yaml")

# Agreement bands (S1a) — reporting thresholds, not gates.
AGREE_HIGH_M = 300.0
AGREE_MEDIUM_M = 2000.0
# Duplicate proximity (S1c).
DUPLICATE_M = 50.0

DEFAULT_DETOUR_THRESHOLD = 1.6


def load_config() -> dict:
    """Read data/config/stations.yaml (simple key: value pairs)."""
    config = {
        "agreement_high_m": AGREE_HIGH_M,
        "agreement_medium_m": AGREE_MEDIUM_M,
        "duplicate_proximity_m": DUPLICATE_M,
        "detour_threshold": DEFAULT_DETOUR_THRESHOLD,
    }
    if not CONFIG.exists():
        return config
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in config and value.strip().replace(".", "", 1).replace("-", "", 1).isdigit():
            config[key] = float(value.strip())
    return config


def name_similarity(a: str, b: str) -> float:
    """Similarity after stripping the 'Stasiun' prefix and normalising."""

    def clean(text: str) -> str:
        upper = normalise_name(text)
        for prefix in ("STASIUN ", "STA "):
            if upper.startswith(prefix):
                upper = upper[len(prefix) :]
        return upper

    left, right = clean(a), clean(b)
    if not left or not right:
        return 0.0
    return round(difflib.SequenceMatcher(None, left, right).ratio(), 3)


def osm_by_code(rows: list[dict]) -> dict[str, list[dict]]:
    """OSM nodes indexed by their ``ref`` tag."""
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        ref = (row.get("tags") or {}).get("ref")
        if not ref or row.get("lat") is None:
            continue
        out[ref.upper()].append(
            {
                "source_id": f"{row['type']}/{row['id']}",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "name": (row.get("tags") or {}).get("name"),
            }
        )
    return out


def triples_from_trips() -> dict[tuple[str, str, str], int]:
    """Count consecutive A-B-C station triples across all loaded trips."""
    triples: Counter[tuple[str, str, str]] = Counter()
    for name in ("intercity_trips.json", "local_trips.json"):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
            for index in range(len(codes) - 2):
                triples[(codes[index], codes[index + 1], codes[index + 2])] += 1
    return triples


def build() -> dict:
    config = load_config()
    matched_path = PARSED / "station_coordinates.json"
    matched = (
        json.loads(matched_path.read_text(encoding="utf-8"))["matched"]
        if matched_path.exists()
        else {}
    )
    overrides = load_overrides()
    override_codes = {o.code: o for o in overrides}

    wd_rows = (
        json.loads((EXTERNAL / "wikidata_stations.json").read_text(encoding="utf-8"))
        if (EXTERNAL / "wikidata_stations.json").exists()
        else []
    )
    # Prefer the Geofabrik-derived station list: the Overpass cache only holds a
    # few hundred nodes, which is too thin for a cross-check.
    osm_rows: list[dict] = []
    graph_path = EXTERNAL / "java_rail_graph.json"
    if graph_path.exists():
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        osm_rows = [
            {
                "type": "node",
                "id": station["id"],
                "lat": station["lat"],
                "lon": station["lon"],
                "tags": {
                    "name": station.get("name"),
                    "ref": station.get("ref"),
                    "railway": station.get("railway"),
                },
            }
            for station in graph.get("stations", [])
        ]
    if not osm_rows and (EXTERNAL / "osm_stations.json").exists():
        osm_rows = json.loads((EXTERNAL / "osm_stations.json").read_text(encoding="utf-8"))
    wd_by_code = wikidata_by_code(wd_rows)
    osm_ref = osm_by_code(osm_rows)
    osm_name = osm_candidates(osm_rows)

    def find_osm(code: str, name: str, wd: list) -> list[dict]:
        """OSM candidates: ref, then exact normalised name, then fuzzy name.

        OSM labels usually omit the "Stasiun" prefix, so a fuzzy match within a
        small radius of the Wikidata point is the practical third tier. Every
        candidate keeps the tier that produced it.
        """
        found = list(osm_ref.get(code.upper(), []))
        if found:
            return found

        exact = [
            {"source_id": c.source_id, "lat": c.lat, "lon": c.lon, "name": c.name}
            for c in osm_name.get(normalise_name(name), [])
        ]
        if exact:
            return exact

        # Fuzzy: only consider OSM stations within 3 km of the Wikidata point, so
        # a name collision elsewhere in Java cannot win.
        if not wd:
            return []
        best = []
        for row in osm_rows:
            label = (row.get("tags") or {}).get("name")
            if not label or row.get("lat") is None:
                continue
            similarity = name_similarity(name, label)
            if similarity < 0.75:
                continue
            km = haversine_km((wd[0].lat, wd[0].lon), (float(row["lat"]), float(row["lon"])))
            if km > 3.0:
                continue
            best.append(
                {
                    "source_id": f"{row['type']}/{row['id']}",
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "name": label,
                    "similarity": similarity,
                    "km_from_wikidata": round(km, 2),
                }
            )
        best.sort(key=lambda c: (-c["similarity"], c["km_from_wikidata"]))
        return best[:3]

    results = []
    band_counts: Counter[str] = Counter()
    low_similarity: list[dict] = []

    for code, entry in sorted(matched.items()):
        wd = wd_by_code.get(code.upper(), [])
        osm = find_osm(code, entry["name"], wd)

        band = "review"
        distance_m = None
        if wd and osm:
            nearest = (
                min(haversine_km((wd[0].lat, wd[0].lon), (o["lat"], o["lon"])) for o in osm) * 1000
            )
            distance_m = round(nearest, 1)
            if nearest <= config["agreement_high_m"]:
                band = "high"
            elif nearest <= config["agreement_medium_m"]:
                band = "medium"
            else:
                band = "review"

        similarity = name_similarity(
            entry["name"], wd[0].name if wd else (osm[0]["name"] if osm else "")
        )
        # A code match alone is never high confidence.
        confidence = entry.get("confidence", "medium")
        if entry.get("match_method") == "code" and similarity < 0.6:
            confidence = "medium"
        if similarity < 0.4:
            low_similarity.append(
                {
                    "code": code,
                    "printed_name": entry["name"],
                    "source_label": wd[0].name if wd else (osm[0]["name"] if osm else None),
                    "similarity": similarity,
                }
            )

        band_counts[band] += 1
        results.append(
            {
                "code": code,
                "printed_name": entry["name"],
                "match_method": entry.get("match_method"),
                "agreement_band": band,
                "wd_osm_distance_m": distance_m,
                "name_similarity": similarity,
                "revised_confidence": confidence,
                "has_osm_candidate": bool(osm),
                "is_override": code in override_codes,
            }
        )

    # (c) neighbour consistency over triples
    triples = triples_from_trips()
    detour_rows = []
    for (a, b, c), count in triples.items():
        pa, pb, pc = matched.get(a), matched.get(b), matched.get(c)
        if not (pa and pb and pc):
            continue
        ab = haversine_km((pa["lat"], pa["lon"]), (pb["lat"], pb["lon"]))
        bc = haversine_km((pb["lat"], pb["lon"]), (pc["lat"], pc["lon"]))
        ac = haversine_km((pa["lat"], pa["lon"]), (pc["lat"], pc["lon"]))
        if ac <= 0.1:
            continue
        ratio = (ab + bc) / ac
        detour_rows.append({"a": a, "b": b, "c": c, "ratio": round(ratio, 2), "count": count})

    ratios = sorted(row["ratio"] for row in detour_rows)
    threshold = config["detour_threshold"]
    flagged_b = Counter(row["b"] for row in detour_rows if row["ratio"] > threshold)

    # (d) duplicate proximity
    duplicates = []
    codes = sorted(matched)
    for i, left in enumerate(codes):
        for right in codes[i + 1 :]:
            d = (
                haversine_km(
                    (matched[left]["lat"], matched[left]["lon"]),
                    (matched[right]["lat"], matched[right]["lon"]),
                )
                * 1000
            )
            if d < config["duplicate_proximity_m"]:
                duplicates.append({"a": left, "b": right, "distance_m": round(d, 1)})

    def quantile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
        return round(values[index], 3)

    return {
        "note": (
            "Independent cross-check of coordinate matches. Nothing is corrected; "
            "every finding is listed for human review."
        ),
        "config": config,
        "checked": len(results),
        "agreement_bands": dict(band_counts),
        "with_osm_candidate": sum(1 for r in results if r["has_osm_candidate"]),
        "low_name_similarity_count": len(low_similarity),
        "low_name_similarity": low_similarity,
        "detour": {
            "triples_measured": len(detour_rows),
            "distribution": {
                "min": ratios[0] if ratios else None,
                "p50": quantile(ratios, 0.5),
                "p95": quantile(ratios, 0.95),
                "p99": quantile(ratios, 0.99),
                "max": ratios[-1] if ratios else None,
            },
            "threshold": threshold,
            "flagged_station_count": len(flagged_b),
            "flagged_stations": dict(sorted(flagged_b.items(), key=lambda kv: -kv[1])),
            "worst": sorted(detour_rows, key=lambda r: -r["ratio"])[:40],
        },
        "duplicate_proximity": {
            "threshold_m": config["duplicate_proximity_m"],
            "count": len(duplicates),
            "pairs": duplicates,
        },
        "stations": results,
    }


def main() -> int:
    payload = build()
    REVIEW.mkdir(parents=True, exist_ok=True)
    (REVIEW / "stations_crosscheck.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"stations checked: {payload['checked']}")
    print(f"agreement bands: {payload['agreement_bands']}")
    print(f"with OSM candidate: {payload['with_osm_candidate']}")
    print(f"low name similarity: {payload['low_name_similarity_count']}")
    print(
        f"detour triples: {payload['detour']['triples_measured']}  "
        f"max ratio: {payload['detour']['distribution']['max']}"
    )
    print(f"flagged stations (detour): {payload['detour']['flagged_station_count']}")
    print(
        f"duplicate pairs <{payload['duplicate_proximity']['threshold_m']} m: "
        f"{payload['duplicate_proximity']['count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
