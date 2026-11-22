"""T2 (V15): cross-check every trip's endpoints against an independent source.

For each trip, the table parser gives a first departure and a last arrival. The
index pages and the Lampiran IV summary tables give the same two times from a
DIFFERENT part of the PDF. Comparing them catches a table that was parsed with
the wrong train number, a truncated first/last row, or a link to the wrong trip.

Nothing is auto-resolved. Every difference is reported with both values and the
source page.

Usage:
    python -m pipeline.v15_endpoints
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/gapeka.db")
PARSED = Path("data/parsed")
REVIEW = Path("data/review")
OUT = REVIEW / "v15_endpoints.json"

TOLERANCE_S = 60


def parse_hhmm(value: str | None) -> int | None:
    """'08:15' -> seconds of day. A value with seconds keeps them."""
    if not value:
        return None
    parts = value.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def circular_delta(a: int, b: int) -> int:
    """Signed difference in seconds, wrapped to +/-12 h (midnight-safe)."""
    delta = (a - b) % 86400
    if delta > 43200:
        delta -= 86400
    return delta


def classify(delta: int | None) -> str:
    if delta is None:
        return "missing"
    if delta == 0:
        return "exact"
    if abs(delta) <= TOLERANCE_S:
        return "within_1min"
    return "larger"


def trip_endpoints() -> dict[str, dict]:
    """First departure and last arrival per trip, from the parsed table."""
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT t.trip_id, t.train_no, t.book, t.relation, t.service_class,"
            " s.seq, s.arrive, s.depart"
            " FROM trips t JOIN stop_times s ON s.trip_id = t.trip_id"
            " ORDER BY t.trip_id, s.seq"
        ).fetchall()
    finally:
        connection.close()

    out: dict[str, dict] = {}
    for trip_id, train_no, book, relation, service_class, _seq, arrive, depart in rows:
        entry = out.setdefault(
            trip_id,
            {
                "trip_id": trip_id,
                "train_no": train_no,
                "book": book,
                "relation": relation,
                "service_class": service_class,
                "first_depart": None,
                "last_arrive": None,
            },
        )
        if depart and entry["first_depart"] is None:
            entry["first_depart"] = depart
        if arrive:
            entry["last_arrive"] = arrive
    return out


def load_source(name: str) -> list[dict]:
    path = PARSED / f"{name}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return payload.get("entries", [])


def source_index(entries: list[dict], source: str) -> dict[tuple[str, str], dict]:
    """Key by (train_no, relation); a duplicate key is reported, not merged."""
    out: dict[tuple[str, str], dict] = {}
    duplicates: set[tuple[str, str]] = set()
    for entry in entries:
        key = (str(entry.get("train_no", "")).strip(), str(entry.get("relation", "")).strip())
        if key in out:
            duplicates.add(key)
            continue
        out[key] = {
            "depart": entry.get("depart"),
            "arrive": entry.get("arrive"),
            "page": (entry.get("provenance") or {}).get("page"),
            "source": source,
        }
    return out, duplicates


def compare() -> dict:
    trips = trip_endpoints()
    sources = {
        "index_intercity": load_source("expected_trains_intercity"),
        "index_local": load_source("expected_trains_local"),
        "summary_lampiran_iv": load_source("summary_tables_lampiran_iv"),
    }

    results = []
    for trip in trips.values():
        key = (trip["train_no"], trip["relation"] or "")
        sources_for_trip = []
        for name, entries in sources.items():
            index, duplicates = source_index(entries, name)
            entry = index.get(key)
            if entry is None:
                # Fall back to the train number alone when the relation differs,
                # but only if it is unique.
                candidates = [
                    value
                    for (train_no, _relation), value in index.items()
                    if train_no == trip["train_no"]
                ]
                if len(candidates) == 1:
                    entry = candidates[0]
            if entry is None:
                sources_for_trip.append({"source": name, "status": "absent", "page": None})
                continue

            parsed_depart = parse_hhmm(trip["first_depart"])
            parsed_arrive = parse_hhmm(trip["last_arrive"])
            source_depart = parse_hhmm(entry["depart"])
            source_arrive = parse_hhmm(entry["arrive"])
            depart_delta = (
                None
                if parsed_depart is None or source_depart is None
                else circular_delta(parsed_depart, source_depart)
            )
            arrive_delta = (
                None
                if parsed_arrive is None or source_arrive is None
                else circular_delta(parsed_arrive, source_arrive)
            )
            sources_for_trip.append(
                {
                    "source": name,
                    "status": "compared",
                    "page": entry["page"],
                    "source_depart": entry["depart"],
                    "source_arrive": entry["arrive"],
                    "parsed_depart": trip["first_depart"],
                    "parsed_arrive": trip["last_arrive"],
                    "depart_delta_s": depart_delta,
                    "arrive_delta_s": arrive_delta,
                    "depart_class": classify(depart_delta),
                    "arrive_class": classify(arrive_delta),
                }
            )
        results.append({**trip, "sources": sources_for_trip})

    return results


def summarise(results: list[dict]) -> dict:
    per_source: dict[str, dict[str, int]] = {}
    larger = []
    absent = []

    for trip in results:
        for source in trip["sources"]:
            name = source["source"]
            bucket = per_source.setdefault(
                name,
                {
                    "exact": 0,
                    "within_1min": 0,
                    "larger": 0,
                    "missing": 0,
                    "absent": 0,
                    "compared": 0,
                },
            )
            if source["status"] == "absent":
                bucket["absent"] += 1
                absent.append(
                    {
                        "trip_id": trip["trip_id"],
                        "train_no": trip["train_no"],
                        "book": trip["book"],
                        "source": name,
                    }
                )
                continue
            bucket["compared"] += 1
            for field in ("depart", "arrive"):
                bucket[source[f"{field}_class"]] += 1
            if "larger" in (source["depart_class"], source["arrive_class"]):
                larger.append(
                    {
                        "trip_id": trip["trip_id"],
                        "train_no": trip["train_no"],
                        "book": trip["book"],
                        "relation": trip["relation"],
                        "source": name,
                        "page": source["page"],
                        "parsed_depart": source["parsed_depart"],
                        "source_depart": source["source_depart"],
                        "depart_delta_s": source["depart_delta_s"],
                        "parsed_arrive": source["parsed_arrive"],
                        "source_arrive": source["source_arrive"],
                        "arrive_delta_s": source["arrive_delta_s"],
                    }
                )

    return {
        "trips": len(results),
        "per_source": per_source,
        "larger": larger,
        "absent": absent,
    }


def main() -> int:
    results = compare()
    summary = summarise(results)
    payload = {
        "note": (
            "V15 endpoint cross-check. A comparison, not a gate: differences are "
            "reported and never auto-resolved. Delta is parsed minus source, wrapped "
            "to +/-12 h so a midnight crossing is not a false difference."
        ),
        "tolerance_s": TOLERANCE_S,
        "summary": summary,
        "trips": results,
    }
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    print(f"wrote {OUT}")
    print(f"trips {summary['trips']}")
    for name, counts in summary["per_source"].items():
        print(f"  {name}: {counts}")
    print(f"  larger differences: {len(summary['larger'])}")
    for row in summary["larger"][:10]:
        print(
            f"    KA {row['train_no']} {row['relation']} "
            f"[{row['source']} p{row['page']}] "
            f"depart {row['parsed_depart']} vs {row['source_depart']}, "
            f"arrive {row['parsed_arrive']} vs {row['source_arrive']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
