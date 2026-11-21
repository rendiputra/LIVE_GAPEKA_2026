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


def load_aliases(path: Path = Path("data/config/station_aliases.yaml")) -> dict:
    """Parse the human-authored station alias file (H1)."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if "stations:" not in text:
        return {}
    block = text.split("stations:", 1)[1]
    aliases: dict[str, dict] = {}
    current: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("   ") and stripped.endswith(":"):
            current = stripped[:-1].strip()
            aliases[current] = {}
            continue
        if current and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            if key in ("official_name", "station_kind", "note"):
                aliases[current][key] = value.strip().strip('"')
    return aliases


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

    aliases = load_aliases()
    for code in sorted(all_codes):
        name = station_names.get(code) or code
        alias = aliases.get(code, {})
        official = alias.get("official_name")
        name_source = "human" if official else "pdf"
        # A rejected coordinate must never be stored on the station row -- UNLESS a
        # human override exists for that code, which supersedes the rejection.
        is_override = any(o.code == code for o in overrides)
        if code in rejected and not is_override:
            effective.pop(code, None)

        entry = effective.get(code)
        if entry is None:
            # "rejected" when a candidate existed but was refused; "missing" when
            # no source ever produced one. The distinction drives the report.
            status = "rejected" if code in rejected else "missing"
            connection.execute(
                "INSERT INTO stations (code, name, official_name, name_source, coord_status)"
                " VALUES (?, ?, ?, ?, ?)",
                (code, name, official, name_source, status),
            )
        else:
            status = entry.get("coord_status", "accepted")
            connection.execute(
                "INSERT INTO stations (code, name, official_name, name_source, lat, lon,"
                " coord_source, coord_source_id, coord_match, coord_confidence,"
                " coord_retrieved, coord_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    code,
                    name,
                    official,
                    name_source,
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

    # --- geometry (Phase 4 output). Only rows whose endpoints exist are loaded. ---
    segments_path = PARSED_DIR / "segments.json"
    geometry_summary = {}
    if segments_path.exists():
        geo = load_json(segments_path)
        existing = {row[0] for row in connection.execute("SELECT code FROM stations")}
        for seg in geo["segments"]:
            if seg["from_code"] not in existing or seg["to_code"] not in existing:
                continue
            connection.execute(
                "INSERT OR REPLACE INTO segments (from_station, to_station, geometry,"
                " length_m, straight_m, detour_ratio, geometry_quality, reason, source_way_ids)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    seg["from_code"],
                    seg["to_code"],
                    json.dumps(seg["geometry"]) if seg["geometry"] else None,
                    seg["length_m"],
                    seg["straight_m"],
                    seg["detour_ratio"],
                    seg["quality"],
                    seg.get("reason", ""),
                    "[]",
                ),
            )

        trip_ids = {
            f"b{book}-{number}-v{VERSION_ID}-{occ:02d}": tid
            for tid, book, number, occ in connection.execute(
                "SELECT trip_id, book, train_no, substr(trip_id, -2) FROM trips"
            ).fetchall()
            for occ in [int(occ)]
        }
        for key, status in geo["trip_status"].items():
            book_s, number = key.split(":", 1)
            tid = None
            for candidate, mapped in trip_ids.items():
                if candidate.startswith(f"b{book_s}-{number}-v"):
                    tid = mapped
                    break
            if tid is None:
                continue
            counts = status["counts"]
            connection.execute(
                "INSERT OR REPLACE INTO trip_geometry_status (trip_id, status,"
                " has_bypassed_waypoints, osm_routed, osm_suspect, straight_line,"
                " unmeasured, total_length_m) VALUES (?,?,?,?,?,?,?,?)",
                (
                    tid,
                    status["status"],
                    1 if status.get("has_bypassed_waypoints") else 0,
                    counts.get("osm_routed", 0),
                    counts.get("osm_suspect", 0),
                    counts.get("straight_line", 0),
                    counts.get("unmeasured", 0),
                    None,
                ),
            )
        geometry_summary = {
            "quality_counts": geo["quality_counts"],
            "trip_status_counts": geo["trip_status_counts"],
            "content_hash": geo["content_hash"],
        }

    # Q4: record every bypassed row so nothing is silently dropped.
    connection.execute("DROP TABLE IF EXISTS trip_waypoint_estimates")
    connection.execute(
        "CREATE TABLE trip_waypoint_estimates ("
        " trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,"
        " seq INTEGER NOT NULL, station_code TEXT NOT NULL,"
        " method TEXT NOT NULL,"
        " PRIMARY KEY (trip_id, seq))"
    )
    if segments_path.exists():
        for key, rows in geo.get("trip_bypass", {}).items():
            book_s, number = key.split(":", 1)
            tid = next(
                (v for k, v in trip_ids.items() if k.startswith(f"b{book_s}-{number}-v")),
                None,
            )
            if tid is None:
                continue
            for row in rows:
                connection.execute(
                    "INSERT OR REPLACE INTO trip_waypoint_estimates"
                    " (trip_id, seq, station_code, method) VALUES (?,?,?,?)",
                    (tid, row["seq"], row["station_code"], "bypass_between_neighbours"),
                )

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
            "segments",
            "trip_geometry_status",
            "trip_waypoint_estimates",
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
        "segments",
        "trip_geometry_status",
        "trip_waypoint_estimates",
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
        "geometry": geometry_summary,
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
    # Persist the summary so every number quoted in a report has a file behind it.
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "db_build.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
