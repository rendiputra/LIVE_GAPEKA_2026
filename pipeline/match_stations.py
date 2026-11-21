"""Match PDF station codes to external coordinates (Phase 3a step 4b).

Matching order, exactly as ruled:

1. **by code** against Wikidata (P296);
2. **by normalised name** against Wikidata labels;
3. **by normalised name** against OSM (railway=station/halt).

Anything with zero candidates goes to ``stations_unmatched.json``; anything with
more than one candidate goes to ``stations_ambiguous.json``. Nothing is resolved
here, and no coordinate is ever interpolated or guessed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from pipeline.cross_checks import haversine_km
from pipeline.station_coords import (
    JAVA_BBOX,
    Candidate,
    normalise_name,
    osm_candidates,
    wikidata_by_code,
    wikidata_by_name,
)

PARSED_DIR = Path("data/parsed")
REVIEW_DIR = Path("data/review")
RETRIEVAL_DATE = date.today().isoformat()


def collect_pdf_stations() -> dict[str, dict]:
    """Every station code observed in the parsed trips, with printed names."""
    stations: dict[str, dict] = defaultdict(
        lambda: {"names": defaultdict(int), "pages": set(), "trains": set()}
    )
    for path in (PARSED_DIR / "intercity_trips.json", PARSED_DIR / "local_trips.json"):
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            for stop in train["stops"]:
                code = stop["station_code"]
                if not code:
                    continue
                entry = stations[code]
                entry["names"][stop["station_name"] or ""] += 1
                entry["pages"].add(stop["provenance"]["page"])
                if train["train_no"]:
                    entry["trains"].add(train["train_no"])
    out = {}
    for code, entry in stations.items():
        # The most frequent printed spelling wins as the display name.
        name = max(entry["names"].items(), key=lambda kv: kv[1])[0]
        out[code] = {
            "code": code,
            "name": name,
            "spellings": dict(entry["names"]),
            "page_count": len(entry["pages"]),
            "occurrences": sum(entry["names"].values()),
            "train_count": len(entry["trains"]),
        }
    return out


def in_java(lat: float, lon: float) -> bool:
    return (
        JAVA_BBOX["min_lat"] <= lat <= JAVA_BBOX["max_lat"]
        and JAVA_BBOX["min_lon"] <= lon <= JAVA_BBOX["max_lon"]
    )


def _accept(candidate: Candidate) -> bool:
    """A single candidate must also be geographically plausible.

    A station code can collide across islands (Wikidata ``TLM`` is a Sumatra
    station while the Gapeka's TLM is "Telaga Murni" in Java). Coordinates
    outside the Java bounding box are therefore treated as a rejected candidate,
    not as a match.
    """
    return in_java(candidate.lat, candidate.lon)


def _rejected_note(code: str, name: str, candidates: list[Candidate], method: str) -> dict:
    return {
        "code": code,
        "name": name,
        "reason": f"{method}_outside_java_bbox",
        "candidates": [_candidate_dict(c, method, "high") for c in candidates],
    }


def _candidate_dict(candidate: Candidate, method: str, confidence: str) -> dict:
    return {
        "source": candidate.source,
        "source_id": candidate.source_id,
        "name": candidate.name,
        "lat": round(candidate.lat, 6),
        "lon": round(candidate.lon, 6),
        "match_method": method,
        "confidence": confidence,
        "retrieved": RETRIEVAL_DATE,
        "in_java_bbox": in_java(candidate.lat, candidate.lon),
    }


def match(
    pdf_stations: dict[str, dict],
    wd_by_code: dict[str, list[Candidate]],
    wd_by_name: dict[str, list[Candidate]],
    osm_by_name: dict[str, list[Candidate]],
) -> dict:
    """Resolve each code to at most one candidate, or record why not."""
    matched: dict[str, dict] = {}
    unmatched: list[dict] = []
    ambiguous: list[dict] = []

    for code, info in sorted(pdf_stations.items()):
        attempts = []

        # 1. code match against Wikidata
        candidates = wd_by_code.get(code.upper(), [])
        plausible = [c for c in candidates if _accept(c)]
        if len(candidates) == 1 and not plausible:
            ambiguous.append(_rejected_note(code, info["name"], candidates, "wikidata_by_code"))
            continue
        candidates = plausible
        if len(candidates) == 1:
            matched[code] = {
                "code": code,
                "name": info["name"],
                **_candidate_dict(candidates[0], "code", "high"),
            }
            continue
        if len(candidates) > 1:
            ambiguous.append(
                {
                    "code": code,
                    "name": info["name"],
                    "reason": "multiple_wikidata_items_for_code",
                    "candidates": [_candidate_dict(c, "code", "high") for c in candidates],
                }
            )
            continue
        attempts.append("wikidata_by_code: none")

        # 2. normalised name match against Wikidata
        key = normalise_name(info["name"])
        candidates = [c for c in wd_by_name.get(key, []) if _accept(c)]
        if len(candidates) == 1:
            matched[code] = {
                "code": code,
                "name": info["name"],
                **_candidate_dict(candidates[0], "name_normalised", "medium"),
            }
            continue
        if len(candidates) > 1:
            ambiguous.append(
                {
                    "code": code,
                    "name": info["name"],
                    "reason": "multiple_wikidata_items_for_name",
                    "candidates": [
                        _candidate_dict(c, "name_normalised", "medium") for c in candidates
                    ],
                }
            )
            continue
        attempts.append("wikidata_by_name: none")

        # 3. normalised name match against OSM
        candidates = [c for c in osm_by_name.get(key, []) if _accept(c)]
        if len(candidates) == 1:
            matched[code] = {
                "code": code,
                "name": info["name"],
                **_candidate_dict(candidates[0], "name_normalised", "medium"),
            }
            continue
        if len(candidates) > 1:
            ambiguous.append(
                {
                    "code": code,
                    "name": info["name"],
                    "reason": "multiple_osm_nodes_for_name",
                    "candidates": [
                        _candidate_dict(c, "name_normalised", "medium") for c in candidates
                    ],
                }
            )
            continue
        attempts.append("osm_by_name: none")

        unmatched.append(
            {
                "code": code,
                "name": info["name"],
                "page_count": info["page_count"],
                "train_count": info["train_count"],
                "attempts": attempts,
            }
        )

    return {
        "matched": matched,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "suspicious": suspicious_coordinates(matched),
    }


def suspicious_coordinates(matched: dict[str, dict]) -> list[dict]:
    """Flag a coordinate that is implausibly far from every route neighbour.

    A single Wikidata item can carry a wrong coordinate (e.g. LR "Larangan
    (Tegal)" is geolocated in Madura, ~111 km from Tegal). The check is
    geometric only: if a station is more than 40 km from BOTH of its most common
    neighbours, its coordinate is suspect. Nothing is corrected here.
    """
    from pipeline.cross_checks import load_trips  # local import avoids a cycle

    neighbours: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for name in ("intercity_trips.json", "local_trips.json"):
        for train in load_trips(name):
            stops = train["stops"]
            for index, stop in enumerate(stops):
                code = stop["station_code"]
                for offset in (-1, 1):
                    position = index + offset
                    if 0 <= position < len(stops):
                        other = stops[position]["station_code"]
                        if other and other != code:
                            neighbours[code][other] += 1

    suspicious = []

    # Duplicate coordinates: two DISTINCT codes on (nearly) the same point means
    # at least one external item is wrong. Distance-based, not exact equality:
    # MLK/SBP sit 15 m apart because SBP was given Malang Kotalama's coordinate.

    codes_sorted = sorted(matched)
    for i, left in enumerate(codes_sorted):
        for right in codes_sorted[i + 1 :]:
            gap_m = (
                haversine_km(
                    (matched[left]["lat"], matched[left]["lon"]),
                    (matched[right]["lat"], matched[right]["lon"]),
                )
                * 1000
            )
            if gap_m > 50.0:
                continue
            suspicious.append(
                {
                    "code": f"{left},{right}",
                    "name": "duplicate coordinates",
                    "lat": matched[left]["lat"],
                    "lon": matched[left]["lon"],
                    "source_id": f"{matched[left]['source_id']}, {matched[right]['source_id']}",
                    "neighbours": [],
                    "neighbour_distances_km": [],
                    "reason": f"two distinct codes only {gap_m:.0f} m apart",
                }
            )

    for code, entry in sorted(matched.items()):
        counts = neighbours.get(code)
        if not counts:
            continue
        nearest_two = sorted(counts.items(), key=lambda kv: -kv[1])[:2]
        distances = []
        for other, _count in nearest_two:
            other_entry = matched.get(other)
            if not other_entry:
                continue
            distances.append(
                haversine_km(
                    (entry["lat"], entry["lon"]),
                    (other_entry["lat"], other_entry["lon"]),
                )
            )
        if distances and all(d > 40.0 for d in distances):
            suspicious.append(
                {
                    "code": code,
                    "name": entry["name"],
                    "lat": entry["lat"],
                    "lon": entry["lon"],
                    "source_id": entry["source_id"],
                    "neighbours": [n for n, _ in nearest_two],
                    "neighbour_distances_km": [round(d, 1) for d in distances],
                }
            )
    return suspicious


def run() -> dict:
    pdf_stations = collect_pdf_stations()

    wd_rows = json.loads((Path("data/external/wikidata_stations.json")).read_text(encoding="utf-8"))
    osm_rows = json.loads((Path("data/external/osm_stations.json")).read_text(encoding="utf-8"))

    result = match(
        pdf_stations,
        wikidata_by_code(wd_rows),
        wikidata_by_name(wd_rows),
        osm_candidates(osm_rows),
    )

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "stations_unmatched.json").write_text(
        json.dumps(
            {
                "note": "No coordinate source matched. Never guessed or interpolated.",
                "count": len(result["unmatched"]),
                "stations": result["unmatched"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (REVIEW_DIR / "stations_ambiguous.json").write_text(
        json.dumps(
            {
                "note": "Multiple candidates. Listed, never resolved.",
                "count": len(result["ambiguous"]),
                "stations": result["ambiguous"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (PARSED_DIR / "station_coordinates.json").write_text(
        json.dumps(
            {
                "retrieved": RETRIEVAL_DATE,
                "pdf_stations": len(pdf_stations),
                "matched": result["matched"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    by_method: dict[str, int] = defaultdict(int)
    for entry in result["matched"].values():
        by_method[entry["match_method"]] += 1

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "stations_suspicious_coords.json").write_text(
        json.dumps(
            {
                "note": (
                    "Coordinate is >40 km from BOTH most common route neighbours. "
                    "Reported, not corrected: a wrong external coordinate is not "
                    "our data to invent."
                ),
                "count": len(result.get("suspicious", [])),
                "stations": result.get("suspicious", []),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "pdf_stations": len(pdf_stations),
        "suspicious": len(result.get("suspicious", [])),
        "matched": len(result["matched"]),
        "unmatched": len(result["unmatched"]),
        "ambiguous": len(result["ambiguous"]),
        "by_method": dict(by_method),
        "out_of_java_bbox": [
            {"code": code, "name": entry["name"], "lat": entry["lat"], "lon": entry["lon"]}
            for code, entry in result["matched"].items()
            if not entry["in_java_bbox"]
        ],
    }


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
