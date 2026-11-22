"""Tests for the verification import (T1).

The rule that matters: a trip is promoted to a golden fixture only when EVERY row
matched. A trip with any wrong row is never promoted, and nothing is fixed.
"""

from __future__ import annotations

import json

import pytest

from pipeline import import_verifications as iv


@pytest.fixture
def result_file(tmp_path):
    def _write(trains):
        payload = {
            "verifier": "human",
            "date": "2026-11-22",
            "method": "visual comparison of PDF page images against the parsed table",
            "trains": trains,
        }
        path = tmp_path / "verification_result.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _write


def test_all_rows_match_promotes_to_golden(result_file):
    path = result_file(
        [
            {
                "trip_id": "b1-1-v1-01",
                "train_no": "1",
                "book": 1,
                "verdict": "all_rows_match",
                "wrong_rows": [],
                "pages": [59],
            }
        ]
    )
    summary = iv.import_result(path, dry_run=True)
    assert len(summary["promoted"]) == 1
    assert summary["findings"] == []


def test_any_wrong_row_blocks_promotion(result_file):
    path = result_file(
        [
            {
                "trip_id": "b1-1-v1-01",
                "train_no": "1",
                "book": 1,
                "verdict": "has_errors",
                "wrong_rows": [{"seq": 3, "note": "waktu salah"}],
                "pages": [59],
            }
        ]
    )
    summary = iv.import_result(path, dry_run=True)
    assert summary["promoted"] == []
    assert len(summary["findings"]) == 1
    finding = summary["findings"][0]
    assert finding["seq"] == 3
    assert finding["note"] == "waktu salah"
    assert finding["status"] == "open"


def test_verdict_all_rows_match_but_with_rows_still_blocks(result_file):
    """Contradictory input must not promote: a wrong row wins."""
    path = result_file(
        [
            {
                "trip_id": "b1-1-v1-01",
                "train_no": "1",
                "book": 1,
                "verdict": "all_rows_match",
                "wrong_rows": [{"seq": 2, "note": ""}],
                "pages": [59],
            }
        ]
    )
    summary = iv.import_result(path, dry_run=True)
    assert summary["promoted"] == []
    assert len(summary["findings"]) == 1


def test_empty_result_is_an_error(result_file):
    path = result_file([])
    with pytest.raises(ValueError):
        iv.import_result(path, dry_run=True)


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        iv.import_result(tmp_path / "nope.json", dry_run=True)


def test_finding_carries_the_parsed_value(result_file):
    """A finding must show what the pipeline currently holds, so it can be checked."""
    path = result_file(
        [
            {
                "trip_id": "b1-1-v1-01",
                "train_no": "1",
                "book": 1,
                "verdict": "has_errors",
                "wrong_rows": [{"seq": 1, "note": "x"}],
                "pages": [59],
            }
        ]
    )
    try:
        summary = iv.import_result(path, dry_run=True)
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")
    if not summary["findings"]:
        pytest.skip("trip b1-1-v1-01 not in this database")
    finding = summary["findings"][0]
    assert "parsed" in finding
    assert "page" in finding
