"""Golden fixtures: every human-verified trip must match the database.

The fixtures in ``tests/golden/verified_*.json`` are written by
``pipeline/import_verifications.py`` after a human compared every row against the
PDF page images. Without this test they were inert data: the fixtures existed but
nothing checked that the database still agreed with what the human signed off.

A mismatch here means the pipeline changed after verification, which invalidates
the verification until it is re-done.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

GOLDEN = Path("tests/golden")
DB = Path("data/gapeka.db")

VERIFIED = sorted(GOLDEN.glob("verified_*.json"))


def _db_stops(connection: sqlite3.Connection, trip_id: str) -> list[dict]:
    rows = connection.execute(
        "SELECT seq, station_code, arrive, depart, day_offset, stop_type,"
        " raw_arrive, raw_depart, keterangan_raw, speed_raw, source_page"
        " FROM stop_times WHERE trip_id = ? ORDER BY seq",
        (trip_id,),
    ).fetchall()
    return [
        {
            "seq": row[0],
            "station_code": row[1],
            "arrive": row[2],
            "depart": row[3],
            "day_offset": row[4],
            "stop_type": row[5],
            "raw_arrive": row[6],
            "raw_depart": row[7],
            "keterangan_raw": row[8],
            "speed_raw": row[9],
            "source_page": row[10],
        }
        for row in rows
    ]


def test_there_are_verified_fixtures():
    """Guard against a silent regression to zero verified trains."""
    assert len(VERIFIED) >= 20, f"expected at least 20 verified fixtures, found {len(VERIFIED)}"


def test_every_fixture_is_marked_human_verified():
    for path in VERIFIED:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("verified_by_human") is True, path.name
        assert payload.get("verifier") == "human", path.name
        assert payload.get("date"), path.name
        assert payload.get("method"), path.name


@pytest.mark.parametrize("path", VERIFIED, ids=[p.stem for p in VERIFIED])
def test_fixture_matches_the_database(path: Path):
    if not DB.exists():
        pytest.skip("database not available")

    payload = json.loads(path.read_text(encoding="utf-8"))
    train = payload["trains"][0]
    trip_id = train["trip_id"]

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        actual = _db_stops(connection, trip_id)
    finally:
        connection.close()

    assert actual, f"trip {trip_id} has no stop_times"
    expected = train["stops"]
    assert len(actual) == len(expected), (
        f"{path.name}: {len(actual)} stop_times in DB vs {len(expected)} verified"
    )

    for want, got in zip(expected, actual, strict=True):
        for field in (
            "seq",
            "station_code",
            "arrive",
            "depart",
            "day_offset",
            "stop_type",
            "raw_arrive",
            "raw_depart",
            "keterangan_raw",
            "speed_raw",
            "source_page",
        ):
            assert got[field] == want[field], (
                f"{path.name} KA {train['train_no']} seq {want['seq']}: "
                f"{field} is {got[field]!r}, human verified {want[field]!r}"
            )
