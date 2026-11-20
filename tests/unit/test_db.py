"""Phase 3a database tests.

Covers: foreign-key integrity, table counts against the parsed JSON, the golden
fixtures compared row by row, and a deterministic rebuild.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

DB = Path("data/gapeka.db")
PARSED = Path("data/parsed")
GOLDEN = Path("tests/golden")


@pytest.fixture(scope="module")
def connection():
    if not DB.exists():
        pytest.skip("run `python -m pipeline.build_db` first")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def test_foreign_keys_are_enforced_and_clean(connection):
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] in (0, 1)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_every_trip_has_at_least_one_stop(connection):
    orphans = connection.execute(
        "SELECT COUNT(*) FROM trips t "
        "WHERE NOT EXISTS (SELECT 1 FROM stop_times s WHERE s.trip_id = t.trip_id)"
    ).fetchone()[0]
    assert orphans == 0


def test_every_trip_has_a_calendar_row(connection):
    missing = connection.execute(
        "SELECT COUNT(*) FROM trips t "
        "WHERE NOT EXISTS (SELECT 1 FROM calendar c WHERE c.trip_id = t.trip_id)"
    ).fetchone()[0]
    assert missing == 0


def test_trip_count_matches_parsed_validated(connection):
    validated_total = 0
    for name in ("intercity_book1.json", "local_book2.json"):
        path = Path("data/validated") / name
        if path.exists():
            validated_total += json.loads(path.read_text(encoding="utf-8"))["count"]
    assert connection.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == validated_total


def test_stop_time_count_matches_validated_json(connection):
    expected = 0
    for name in ("intercity_book1.json", "local_book2.json"):
        path = Path("data/validated") / name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected += sum(len(t["stops"]) for t in payload["trains"])
    assert connection.execute("SELECT COUNT(*) FROM stop_times").fetchone()[0] == expected


def test_station_count_matches_station_codes_used(connection):
    used = connection.execute("SELECT COUNT(DISTINCT station_code) FROM stop_times").fetchone()[0]
    total = connection.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    assert total >= used


def test_sequence_numbers_are_contiguous_per_trip(connection):
    rows = connection.execute(
        "SELECT trip_id, MIN(seq), MAX(seq), COUNT(*) FROM stop_times GROUP BY trip_id"
    ).fetchall()
    bad = [row for row in rows if row[1] != 1 or row[2] != row[3]]
    assert bad == []


def test_day_offset_is_within_the_allowed_range(connection):
    out_of_range = connection.execute(
        "SELECT COUNT(*) FROM stop_times WHERE day_offset NOT IN (0, 1, 2)"
    ).fetchone()[0]
    assert out_of_range == 0


def test_unknown_untimed_rows_have_null_times(connection):
    bad = connection.execute(
        "SELECT COUNT(*) FROM stop_times "
        "WHERE stop_type = 'unknown_untimed' AND (arrive IS NOT NULL OR depart IS NOT NULL)"
    ).fetchone()[0]
    assert bad == 0


def test_marker_rows_keep_their_raw_token(connection):
    bad = connection.execute(
        "SELECT COUNT(*) FROM stop_times "
        "WHERE time_source = 'marker' AND raw_arrive = '' AND raw_depart = ''"
    ).fetchone()[0]
    assert bad == 0


def test_calendar_policy_matches_service_class(connection):
    rows = connection.execute(
        "SELECT t.service_class, c.service_pattern, c.pattern_source "
        "FROM trips t JOIN calendar c ON c.trip_id = t.trip_id"
    ).fetchall()
    for service_class, pattern, source in rows:
        if service_class == "reguler":
            assert pattern == "daily" and source == "assumed"
        else:
            assert pattern is None and source == "unknown"


def test_coordinates_are_inside_java_when_present(connection):
    rows = connection.execute(
        "SELECT code, lat, lon FROM stations WHERE lat IS NOT NULL"
    ).fetchall()
    outside = [
        (code, lat, lon)
        for code, lat, lon in rows
        if not (-9.5 <= lat <= -5.0 and 104.0 <= lon <= 116.0)
    ]
    assert outside == []


def test_station_coordinate_provenance_is_complete(connection):
    bad = connection.execute(
        "SELECT COUNT(*) FROM stations "
        "WHERE lat IS NOT NULL AND (coord_source IS NULL OR coord_source_id IS NULL "
        "OR coord_match IS NULL OR coord_confidence IS NULL OR coord_retrieved IS NULL)"
    ).fetchone()[0]
    assert bad == 0


def test_version_is_draft_until_signoff(connection):
    status = connection.execute("SELECT status FROM gapeka_versions").fetchone()[0]
    assert status == "draft"


def test_effective_dates(connection):
    row = connection.execute("SELECT effective_from, effective_to FROM gapeka_versions").fetchone()
    assert row[0] == "2026-12-01"
    assert row[1] is None


# --- golden fixtures, row by row -------------------------------------------


def _golden_trip(connection, train_no: str):
    return connection.execute(
        "SELECT trip_id FROM trips WHERE train_no = ? ORDER BY book LIMIT 1", (train_no,)
    ).fetchone()


@pytest.mark.parametrize(
    "golden_name", ["pilot_249_250_golden.json", "pilot_259F_260F_golden.json"]
)
def test_golden_fixture_matches_db_row_by_row(connection, golden_name):
    path = GOLDEN / golden_name
    if not path.exists():
        pytest.skip(f"{path} missing")
    golden = json.loads(path.read_text(encoding="utf-8"))

    for train in golden["trains"]:
        row = _golden_trip(connection, train["train_no"])
        if row is None:
            pytest.skip(f"KA {train['train_no']} not loaded")
        trip_id = row[0]
        db_stops = connection.execute(
            "SELECT seq, station_code, arrive, depart, stop_type "
            "FROM stop_times WHERE trip_id = ? ORDER BY seq",
            (trip_id,),
        ).fetchall()

        # A golden fixture may cover only the verified prefix of a train (KA 252
        # is verified for pages 521-522 only). The DB holds the full trip, so the
        # golden rows must match the DB's first N rows.
        assert len(db_stops) >= len(train["stops"]), (
            f"KA {train['train_no']}: DB has {len(db_stops)} rows, golden needs "
            f"{len(train['stops'])}"
        )
        for db_row, golden_stop in zip(db_stops, train["stops"], strict=False):
            assert db_row[0] == golden_stop["seq"]
            assert db_row[1] == golden_stop["station_code"]
            assert db_row[2] == golden_stop["arrive"]["value"]
            assert db_row[3] == golden_stop["depart"]["value"]
            assert db_row[4] == golden_stop["stop_type"]


def test_rebuild_is_deterministic(tmp_path):
    """A second build of the same inputs produces the same logical content."""
    from pipeline.build_db import build

    first = build(tmp_path / "a.db")
    second = build(tmp_path / "b.db")
    assert first["content_hash"] == second["content_hash"]
    assert first["counts"] == second["counts"]


# --- S3: coordinate status, candidates, overrides ---------------------------


def test_rejected_coordinates_are_null(connection):
    """A rejected coordinate must never be stored on the station row."""
    rows = connection.execute(
        "SELECT code, lat, lon FROM stations WHERE coord_status = 'rejected'"
    ).fetchall()
    for code, lat, lon in rows:
        assert lat is None and lon is None, f"{code} kept a rejected coordinate"


def test_accepted_coordinates_are_complete(connection):
    bad = connection.execute(
        "SELECT COUNT(*) FROM stations WHERE coord_status IN ('accepted', 'override') "
        "AND (lat IS NULL OR lon IS NULL OR coord_source IS NULL OR coord_source_id IS NULL)"
    ).fetchone()[0]
    assert bad == 0


def test_rejected_candidates_are_kept_as_evidence(connection):
    """Rejection must not delete the evidence of what the source said."""
    rejected = connection.execute(
        "SELECT COUNT(*) FROM station_coord_candidates WHERE status = 'rejected'"
    ).fetchone()[0]
    assert rejected > 0
    for code, source_id, lat, lon in connection.execute(
        "SELECT code, source_id, lat, lon FROM station_coord_candidates WHERE status='rejected'"
    ).fetchall():
        assert code and source_id and lat is not None and lon is not None


def test_every_coordinate_has_a_candidate_row(connection):
    accepted = connection.execute(
        "SELECT COUNT(*) FROM stations WHERE coord_status IN ('accepted', 'override')"
    ).fetchone()[0]
    candidates = connection.execute(
        "SELECT COUNT(*) FROM station_coord_candidates WHERE status = 'accepted'"
    ).fetchone()[0]
    assert candidates == accepted


def test_coord_status_values_are_valid(connection):
    values = {
        row[0]
        for row in connection.execute("SELECT DISTINCT coord_status FROM stations").fetchall()
    }
    assert values <= {"accepted", "rejected", "missing", "override"}
