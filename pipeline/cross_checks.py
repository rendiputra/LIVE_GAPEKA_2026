"""Phase 3a cross-book checks and distance sanity (report only).

Nothing here merges or resolves. Two books, one station master: a train number can
legitimately appear in both, and that must be visible rather than silently
deduplicated.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

PARSED_DIR = Path("data/parsed")
REVIEW_DIR = Path("data/review")
OUTLIER_KM = 60.0


def load_trips(name: str) -> list[dict]:
    path = PARSED_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["trains"]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


def cross_book(book1: list[dict], book2: list[dict]) -> dict:
    """Train numbers present in both books, and identical-looking trips."""
    b1 = defaultdict(list)
    b2 = defaultdict(list)
    for train in book1:
        if train["train_no"]:
            b1[train["train_no"]].append(train)
    for train in book2:
        if train["train_no"]:
            b2[train["train_no"]].append(train)

    both = sorted(set(b1) & set(b2))

    signatures: dict[tuple, list[dict]] = defaultdict(list)
    for book, trains in ((1, book1), (2, book2)):
        for train in trains:
            first_depart = next(
                (s["depart"]["value"] for s in train["stops"] if s["depart"]["value"]),
                None,
            )
            signatures[
                (train["train_no"], f"{train['origin']}-{train['destination']}", first_depart)
            ].append({"book": book, "page": train["page"]})

    duplicates = {
        "|".join(str(part) for part in key): entries
        for key, entries in signatures.items()
        if len(entries) > 1
    }

    multi_number = [
        {
            "book": book,
            "train_no": train["train_no"],
            "relation": f"{train['origin']}-{train['destination']}",
            "transport": "day_offset" if any(s["day_offset"] > 0 for s in train["stops"]) else "",
        }
        for book, trains in ((1, book1), (2, book2))
        for train in trains
        if train["train_no"] and "-" in train["train_no"]
    ]

    return {
        "note": "Report only. Books are never merged.",
        "book1_trains": len(book1),
        "book2_trains": len(book2),
        "train_numbers_in_both_books": both,
        "train_numbers_in_both_count": len(both),
        "identical_trip_signatures": duplicates,
        "identical_signature_count": len(duplicates),
        "multi_number_trains": multi_number,
        "multi_number_count": len(multi_number),
        "trip_id_rule": (
            "{book}-{train_no}-v{version}-{occurrence:02d}; occurrence disambiguates a "
            "train number repeated within the same book"
        ),
    }


def distance_outliers(trains: list[dict], coordinates: dict[str, dict]) -> dict:
    """Straight-line distance for every consecutive stop pair. Outliers listed."""
    outliers = []
    station_hits: dict[str, int] = defaultdict(int)
    total_pairs = 0
    missing_coords = 0

    for train in trains:
        stops = train["stops"]
        for previous, current in zip(stops, stops[1:], strict=False):
            a = coordinates.get(previous["station_code"])
            b = coordinates.get(current["station_code"])
            if not a or not b:
                missing_coords += 1
                continue
            total_pairs += 1
            km = haversine_km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
            if km > OUTLIER_KM:
                outliers.append(
                    {
                        "train_no": train["train_no"],
                        "from": previous["station_code"],
                        "to": current["station_code"],
                        "km": round(km, 1),
                        "seq_from": previous["seq"],
                        "seq_to": current["seq"],
                    }
                )
                station_hits[previous["station_code"]] += 1
                station_hits[current["station_code"]] += 1

    return {
        "note": (
            "Straight-line distance between consecutive stops. A large value can be "
            "a genuine long non-stop run OR a wrong coordinate or station order."
        ),
        "pairs_measured": total_pairs,
        "pairs_missing_coordinates": missing_coords,
        "outlier_threshold_km": OUTLIER_KM,
        "outlier_count": len(outliers),
        "outliers": sorted(outliers, key=lambda o: -o["km"])[:200],
        "stations_in_outliers": dict(sorted(station_hits.items(), key=lambda kv: -kv[1])),
    }


def name_conflict_evidence(trains: list[dict], coordinates: dict[str, dict]) -> dict:
    """Evidence for the two name conflicts: neighbours and candidate coordinates."""
    conflicts = {"KARANGSARI": ["KRAI", "KRR"], "LARANGAN": ["LR", "LRA"]}
    neighbours: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for train in trains:
        stops = train["stops"]
        for index, stop in enumerate(stops):
            code = stop["station_code"]
            for name, codes in conflicts.items():
                if code not in codes:
                    continue
                before = stops[index - 1]["station_code"] if index > 0 else None
                after = stops[index + 1]["station_code"] if index + 1 < len(stops) else None
                bucket = neighbours[name][code]
                if len(bucket) < 8:
                    bucket.append(
                        {
                            "train_no": train["train_no"],
                            "seq": stop["seq"],
                            "previous": before,
                            "next": after,
                        }
                    )

    out = {}
    for name, codes in conflicts.items():
        out[name] = {}
        for code in codes:
            out[name][code] = {
                "coordinate": coordinates.get(code),
                "neighbour_samples": neighbours[name].get(code, []),
            }
    return {
        "note": "Evidence only; the conflict is NOT resolved here.",
        "conflicts": out,
    }


def run() -> dict:
    book1 = load_trips("intercity_trips.json")
    book2 = load_trips("local_trips.json")
    coords_path = PARSED_DIR / "station_coordinates.json"
    coordinates = (
        json.loads(coords_path.read_text(encoding="utf-8"))["matched"]
        if coords_path.exists()
        else {}
    )

    result = {
        "cross_book": cross_book(book1, book2),
        "distance": distance_outliers(book1 + book2, coordinates),
        "name_conflicts": name_conflict_evidence(book1 + book2, coordinates),
    }

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "station_name_conflict_evidence.json").write_text(
        json.dumps(result["name_conflicts"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    summary = run()
    print(
        json.dumps(
            {
                "train_numbers_in_both": summary["cross_book"]["train_numbers_in_both_count"],
                "identical_signatures": summary["cross_book"]["identical_signature_count"],
                "multi_number_trains": summary["cross_book"]["multi_number_count"],
                "distance_outliers": summary["distance"]["outlier_count"],
            },
            indent=2,
        )
    )
