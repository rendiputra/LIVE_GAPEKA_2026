"""Tests for the Phase 2a validators and the quarantine gate.

Each validator gets a positive and a negative case, as required.
"""

from __future__ import annotations

import pytest

from pipeline.parse_intercity import (
    audit_pass_rows,
    quarantine_reasons,
    validate_v4,
    validate_v8,
    validate_v9,
)
from pipeline.parsers.stop_table import Cell, ParsedTrain, Stop


def make_stop(seq, arrive, depart, code="AA", speed="100", raw_arrive=None, raw_depart=None):
    return Stop(
        seq=seq,
        station_name=None,
        station_code=code,
        speed=Cell(speed, speed, 1, None),
        arrive=Cell(arrive, raw_arrive if raw_arrive is not None else (arrive or "-"), 1, None),
        depart=Cell(depart, raw_depart if raw_depart is not None else (depart or "-"), 1, None),
        note=Cell(None, "", 1, None),
        stop_type="pass" if (raw_arrive or "").upper() == "LS" else "stop",
        provenance={"page": 1},
    )


def make_train(train_no, origin, destination, stops, completeness="complete"):
    return ParsedTrain(
        train_no=train_no,
        name="N",
        origin=origin,
        destination=destination,
        page=1,
        header_y=0.0,
        stops=stops,
        completeness=completeness,
    )


# --- V8 ---------------------------------------------------------------------


def test_v8_passes_when_endpoints_match():
    train = make_train(
        "1",
        "AA",
        "CC",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "09:00:00", None, "CC")],
    )
    report = validate_v8([train])
    assert report["violations"] == []
    assert report["passed"] == 1


def test_v8_fails_when_first_station_differs_from_origin():
    train = make_train(
        "1",
        "AA",
        "CC",
        [make_stop(1, None, "08:00:00", "ZZ"), make_stop(2, "09:00:00", None, "CC")],
    )
    report = validate_v8([train])
    assert len(report["violations"]) == 1
    assert "origin" in report["violations"][0]["problems"][0]


def test_v8_reports_multi_number_train_instead_of_checking():
    train = make_train(
        "42-43",
        "AA",
        "CC",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "09:00:00", None, "CC")],
    )
    report = validate_v8([train])
    assert report["violations"] == []
    assert report["reported_not_checked"] == 1


def test_v8_does_not_require_destination_on_truncated_trip():
    train = make_train(
        "1",
        "AA",
        "CC",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "08:30:00", None, "BB")],
        completeness="truncated_at_loaded_pages",
    )
    report = validate_v8([train])
    assert report["violations"] == []


# --- V9 ---------------------------------------------------------------------


def test_v9_finds_single_train_pairs():
    train = make_train(
        "1",
        "AA",
        "BB",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "09:00:00", None, "BB")],
    )
    report = validate_v9([train])
    assert report["single_train_pair_count"] == 1
    assert report["segments"] == 1


def test_v9_flags_outlier_against_median():
    fast = make_train(
        "1",
        "AA",
        "BB",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "08:10:00", None, "BB")],
    )
    fast2 = make_train(
        "2",
        "AA",
        "BB",
        [make_stop(1, None, "09:00:00", "AA"), make_stop(2, "09:10:00", None, "BB")],
    )
    slow = make_train(
        "3",
        "AA",
        "BB",
        [make_stop(1, None, "10:00:00", "AA"), make_stop(2, "11:00:00", None, "BB")],
    )
    report = validate_v9([fast, fast2, slow])
    assert report["outlier_count"] >= 1
    assert any(o["train_no"] == "3" for o in report["outliers"])


# --- V4 ---------------------------------------------------------------------


def _index_entry(train_no, printed, mapped):
    return {
        "seq": "1",
        "train_no": train_no,
        "name": "N",
        "relation": "AA-BB",
        "printed_page": printed,
        "mapped_pdf_page": mapped,
    }


def test_v4_reports_parsed_not_in_index():
    train = make_train(
        "9",
        "AA",
        "BB",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "09:00:00", None, "BB")],
    )
    report = validate_v4([train], [_index_entry("1", "2", 59)], [(58, 664, 57)])
    assert report["in_tables_not_in_index"] == ["9"]
    assert report["in_both"] == 0


def test_v4_ignores_page_mismatch_for_multi_number_rows():
    train = make_train(
        "41",
        "AA",
        "BB",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "09:00:00", None, "BB")],
    )
    index = [_index_entry("44-41", "95", 152)]
    report = validate_v4([train], index, [(58, 664, 57)])
    assert report["page_mismatch_count"] == 0


def test_v4_reports_page_mismatch_for_simple_train():
    stop = make_stop(1, None, "08:00:00", "AA")
    stop.provenance["page"] = 200
    train = make_train("7", "AA", "BB", [stop, make_stop(2, "09:00:00", None, "BB")])
    report = validate_v4([train], [_index_entry("7", "100", 157)], [(58, 664, 57)])
    assert report["page_mismatch_count"] == 1


# --- gate -------------------------------------------------------------------


def test_gate_quarantines_truncated_train():
    train = make_train(
        "1", "AA", "BB", [make_stop(1, None, "08:00:00", "AA")], "truncated_at_loaded_pages"
    )
    assert "completeness:truncated_at_loaded_pages" in quarantine_reasons(train)


def test_gate_quarantines_stop_with_needs_review():
    stop = make_stop(1, None, "08:00:00", "AA")
    stop.needs_review = ["arrive_unrecognised:Berh"]
    train = make_train("1", "AA", "BB", [stop])
    assert any("arrive_unrecognised" in r for r in quarantine_reasons(train))


def test_gate_passes_clean_train():
    train = make_train(
        "1",
        "AA",
        "BB",
        [make_stop(1, None, "08:00:00", "AA"), make_stop(2, "09:00:00", None, "BB")],
    )
    assert quarantine_reasons(train) == []


# --- pass-row audit ---------------------------------------------------------


def test_audit_counts_ls_rows_without_time_as_counter_example():
    stops = [
        make_stop(1, None, "08:00:00", "AA"),
        make_stop(2, None, None, "BB", raw_arrive="LS", raw_depart="-"),
        make_stop(3, "09:00:00", None, "CC"),
    ]
    train = make_train("1", "AA", "CC", stops)
    audit = audit_pass_rows([train])
    assert audit["ls_rows"] == 1
    assert len(audit["ls_without_any_time"]) == 1


def test_audit_clean_ls_row_has_no_counter_example():
    stops = [
        make_stop(1, None, "08:00:00", "AA"),
        make_stop(2, None, "08:30:00", "BB", raw_arrive="LS"),
        make_stop(3, "09:00:00", None, "CC"),
    ]
    train = make_train("1", "AA", "CC", stops)
    audit = audit_pass_rows([train])
    assert audit["counter_example_count"] == 0


@pytest.mark.parametrize("missing", ["AA", "BB"])
def test_v8_catches_either_endpoint(missing):
    stops = [
        make_stop(1, None, "08:00:00", "AA" if missing != "AA" else "ZZ"),
        make_stop(2, "09:00:00", None, "BB" if missing != "BB" else "YY"),
    ]
    train = make_train("1", "AA", "BB", stops)
    assert len(validate_v8([train])["violations"]) == 1
