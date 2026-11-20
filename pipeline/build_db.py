"""Phase 3a: assemble the validated MVP slice into SQLite.

Deterministic and idempotent. Only **validated** trains are loaded; quarantined
and truncated trains are written to ``data/review/db_skipped.json`` with reasons.

``trip_id`` is deterministic and documented::

    {book}-{train_no}-{version}-{seq_of_occurrence}

where ``seq_of_occurrence`` disambiguates a train number that appears more than
once in the same book (it is 1 for the common case). This makes a rebuild
byte-identical without depending on insertion order.

Usage:
    python -m pipeline.build_db [--db data/gapeka.db]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from pipeline.station_overrides import apply_to as apply_overrides
from pipeline.station_overrides import load as load_overrides

PARSED_DIR = Path("data/parsed")
VALIDATED_DIR = Path("data/validated")
REVIEW_DIR = Path("data/review")
DB_PATH = Path("data/gapeka.db")
SCHEMA = Path("db/schema.sql")

VERSION_ID = 1
VERSION_NAME = "Gapeka 2026"
EFFECTIVE_FROM = "2026-12-01"
EFFECTIVE_TO = None
PDF_SHA256 = "5149c60ca7a739081bf32e13779bd574f89f2e4665fb5e2b1dcda247899710a4"

BOOKS = [
    (1, "intercity_book1.json", "intercity_trips.json"),
    (2, "local_book2.json", "local_trips.json"),
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trip_id(book: int, train_no: str, occurrence: int) -> str:
    """Deterministic trip identifier (documented above)."""
    safe = train_no.replace(" ", "")
    return f"b{book}-{safe}-v{VERSION_ID}-{occurrence:02d}"


def calendar_row(service_class: str) -> tuple[str | None, str, str | None, str | None]:
    """Map service_class to the calendar policy (ADR 002).

    reguler    -> daily, but only as an ASSUMPTION (the PDF states nothing);
    fakultatif -> no pattern, source unknown;
    unknown    -> same as fakultatif.
    """
    if service_class == "reguler":
        return ("daily", "assumed", EFFECTIVE_FROM, None)
    return (None, "unknown", None, None)


def build(db_path: Path = DB_PATH) -> dict:
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    connection.execute("PRAGMA foreign_keys = ON")

    connection.execute(
        "INSERT INTO gapeka_versions (id, name, effective_from, effective_to,"
        " pdf_sha256, status, notes) VALUES (?, ?, ?, ?, ?, 'draft', ?)",
        (
            VERSION_ID,
            VERSION_NAME,
            EFFECTIVE_FROM,
            EFFECTIVE_TO,
            PDF_SHA256,
            "status stays draft until human sign-off (ADR 002)",
        ),
    )

    # --- coordinates: accepted matches, rejected evidence, human overrides ---
    coordinates = {}
    coord_path = PARSED_DIR / "station_coordinates.json"
    if coord_path.exists():
        coordinates = load_json(coord_path)["matched"]

    # Rejected candidates come from the cross-check artefacts; they are evidence,
    # never used for geometry.
    rejected: dict[str, list[dict]] = {}
    suspicious_path = REVIEW_DIR / "stations_suspicious_coords.json"
    if suspicious_path.exists():
        for row in load_json(suspicious_path)["stations"]:
            for code in row["code"].split(","):
                rejected.setdefault(code.strip(), []).append(
                    {
                        "source": "wikidata",
                        "source_id": row["source_id"].split(",")[0].strip(),
                        "lat": row["lat"],
                        "lon": row["lon"],
                        "reason": row.get("reason") or "implausible neighbour distance",
                    }
                )

    overrides = load_overrides()
    effective = apply_overrides(overrides, coordinates)

    # Every station code the trips use must exist before trips reference it.
    station_names: dict[str, str] = {}
    all_codes: set[str] = set()
    trains_seen: dict[str, dict] = {}
    for _book, _validated_name, parsed_name in BOOKS:
        parsed_file = PARSED_DIR / parsed_name
        if not parsed_file.exists():
            continue
        for train in load_json(parsed_file)["trains"]:
            trains_seen.setdefault(
                train["train_no"],
                {
                    "train_no": train["train_no"],
                    "name": train["name"],
                    "class": train.get("service_class"),
                    "relation": f"{train['origin']}-{train['destination']}",
                },
            )
            for stop in train["stops"]:
                if stop["station_code"]:
                    all_codes.add(stop["station_code"])
                    if stop["station_name"]:
                        station_names.setdefault(stop["station_code"], stop["station_name"])

    for code in sorted(all_codes):
        name = station_names.get(code) or code
        # A rejected coordinate must never be stored on the station row.
        if code in rejected:
            effective.pop(code, None)

        entry = effective.get(code)
        if entry is None:
            # "rejected" when a candidate existed but was refused; "missing" when
            # no source ever produced one. The distinction drives the report.
            status = "rejected" if code in rejected else "missing"
            connection.execute(
                "INSERT INTO stations (code, name, coord_status) VALUES (?, ?, ?)",
                (code, name, status),
            )
        else:
            status = entry.get("coord_status", "accepted")
            connection.execute(
                "INSERT INTO stations (code, name, lat, lon, coord_source, coord_source_id,"
                " coord_match, coord_confidence, coord_retrieved, coord_status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    code,
                    name,
                    entry["lat"],
                    entry["lon"],
                    entry["source"],
                    entry["source_id"],
                    entry["match_method"],
                    entry["confidence"],
                    entry["retrieved"],
                    status,
                ),
            )

        # Evidence rows: accepted candidate, plus every rejected one.
        if entry is not None:
            connection.execute(
                "INSERT OR IGNORE INTO station_coord_candidates"
                " (code, source, source_id, lat, lon, status, reason, retrieved_on)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    code,
                    entry["source"],
                    entry["source_id"],
                    entry["lat"],
                    entry["lon"],
                    "accepted",
                    entry.get("reason", "matched from external source"),
                    entry["retrieved"],
                ),
            )
        for bad in rejected.get(code, []):
            connection.execute(
                "INSERT OR IGNORE INTO station_coord_candidates"
                " (code, source, source_id, lat, lon, status, reason, retrieved_on)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    code,
                    bad["source"],
                    bad["source_id"],
                    bad["lat"],
                    bad["lon"],
                    "rejected",
                    bad["reason"],
                    "2026-11-20",
                ),
            )

    for number, info in sorted(trains_seen.items()):
        connection.execute(
            "INSERT OR REPLACE INTO trains (train_no, name, class, relation) VALUES (?,?,?,?)",
            (number, info["name"], info["class"], info["relation"]),
        )

    skipped: list[dict] = []
    loaded_trips = 0
    loaded_stops = 0
    station_codes: set[str] = set()
    class_counts: Counter[str] = Counter()
    untimed_trains = 0

    for book, validated_name, parsed_name in BOOKS:
        validated_path = VALIDATED_DIR / validated_name
        parsed_path = PARSED_DIR / parsed_name
        if not validated_path.exists():
            continue

        validated = load_json(validated_path)
        validated_numbers = {t["train_no"] for t in validated["trains"]}

        # Anything parsed but not validated is recorded with a reason.
        if parsed_path.exists():
            for train in load_json(parsed_path)["trains"]:
                if train["train_no"] in validated_numbers:
                    continue
                reason = (
                    "truncated_at_loaded_pages"
                    if train["completeness"] != "complete"
                    else "quarantined_or_unvalidated"
                )
                skipped.append(
                    {
                        "book": book,
                        "train_no": train["train_no"],
                        "reason": reason,
                        "completeness": train["completeness"],
                        "needs_review": train["needs_review"],
                    }
                )

        occurrence: Counter[str] = Counter()
        for train in validated["trains"]:
            number = train["train_no"]
            occurrence[number] += 1
            tid = trip_id(book, number, occurrence[number])

            pages = sorted({stop["provenance"]["page"] for stop in train["stops"]})
            has_markers = any(stop["stop_type"] == "unknown_untimed" for stop in train["stops"])
            if has_markers:
                untimed_trains += 1

            connection.execute(
                "INSERT INTO trips (trip_id, train_no, version_id, book, service_class,"
                " service_class_source, completeness, has_untimed_markers, relation,"
                " origin, destination, source_pages, needs_review)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    tid,
                    number,
                    VERSION_ID,
                    book,
                    train.get("service_class", "unknown"),
                    train.get("service_class_source", "unknown"),
                    train["completeness"],
                    1 if has_markers else 0,
                    f"{train['origin']}-{train['destination']}",
                    train["origin"],
                    train["destination"],
                    json.dumps(pages),
                    json.dumps(train["needs_review"]),
                ),
            )
            loaded_trips += 1
            class_counts[train.get("service_class", "unknown")] += 1

            trains_seen.setdefault(
                number,
                {
                    "train_no": number,
                    "name": train["name"],
                    "class": train.get("service_class"),
                    "relation": f"{train['origin']}-{train['destination']}",
                },
            )

            pattern, source, valid_from, valid_to = calendar_row(
                train.get("service_class", "unknown")
            )
            connection.execute(
                "INSERT INTO calendar (trip_id, service_pattern, pattern_source,"
                " valid_from, valid_to) VALUES (?,?,?,?,?)",
                (tid, pattern, source, valid_from, valid_to),
            )

            for stop in train["stops"]:
                code = stop["station_code"]
                station_codes.add(code)
                # A marker row has two cells; report the dominant source.
                sources = [stop["arrive"]["source"], stop["depart"]["source"]]
                if "marker" in sources:
                    time_source = "marker"
                elif "printed" in sources:
                    time_source = "printed"
                elif "empty" in sources:
                    time_source = "empty"
                else:
                    time_source = "not_printed"

                connection.execute(
                    "INSERT INTO stop_times (trip_id, seq, station_code, arrive, depart,"
                    " day_offset, stop_type, time_source, raw_arrive, raw_depart, estimated,"
                    " speed_raw, keterangan_raw, source_page, needs_review)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        stop["seq"],
                        code,
                        stop["arrive"]["value"],
                        stop["depart"]["value"],
                        stop["day_offset"],
                        stop["stop_type"],
                        time_source,
                        stop["arrive"]["raw"],
                        stop["depart"]["raw"],
                        1
                        if (stop["arrive"].get("estimated") or stop["depart"].get("estimated"))
                        else 0,
                        stop["speed"]["raw"],
                        stop["note"]["raw"],
                        stop["provenance"]["page"],
                        json.dumps(stop["needs_review"]),
                    ),
                )
                loaded_stops += 1

    connection.commit()

    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "gapeka_versions",
            "stations",
            "trains",
            "trips",
            "stop_times",
            "calendar",
            "station_coord_candidates",
        )
    }
    station_coords = connection.execute(
        "SELECT COUNT(*) FROM stations WHERE lat IS NOT NULL"
    ).fetchone()[0]

    # A logical content hash: independent of row insertion order.
    digest = hashlib.sha256()
    for table in (
        "gapeka_versions",
        "stations",
        "trains",
        "trips",
        "stop_times",
        "calendar",
        "station_coord_candidates",
    ):
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        digest.update(table.encode())
        for row in rows:
            digest.update(json.dumps(row, default=str, sort_keys=True).encode())

    connection.close()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "db_skipped.json").write_text(
        json.dumps(
            {
                "note": "Parsed but NOT loaded: quarantined or truncated trains.",
                "count": len(skipped),
                "trains": skipped,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "db": str(db_path),
        "counts": counts,
        "stations_with_coordinates": station_coords,
        "content_hash": digest.hexdigest(),
        "skipped": len(skipped),
        "service_class": dict(class_counts),
        "trips_with_untimed_markers": untimed_trains,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the MVP SQLite database.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)

    summary = build(args.db)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
