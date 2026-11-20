"""Tests for the station-code sweep (V3b), the index parser, and the doctor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.doctor import _check_raw_words
from pipeline.parsers.index_table import (
    RELATION_RE,
    TRAIN_NO_RE,
    _bands,
    parse_index_pages,
    parse_index_row,
)
from pipeline.parsers.table_geometry import Word, words_from_raw
from pipeline.station_codes import (
    CodeNameIndex,
    _edit_distance,
    near_duplicates,
    prefix_pairs,
    scan_payload,
    v3b_report,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def word(x0, y0, text, block=0, line=0, index=0) -> Word:
    return Word(x0=x0, y0=y0, x1=x0 + 20, y1=y0 + 7, text=text, block=block, line=line, word=index)


# --- V3b: station codes -----------------------------------------------------


def test_station_row_yields_name_and_code():
    index = CodeNameIndex()
    payload = {
        "words": [
            [55, 100, 65, 113, "1", 0, 0, 0],
            [72, 100, 100, 113, "Semarang", 0, 1, 0],
            [103, 100, 123, 113, "Poncol", 0, 2, 0],
            [127, 100, 150, 113, "(SMC)", 0, 3, 0],
            [233, 100, 236, 113, "100", 0, 4, 0],
            [268, 100, 303, 113, "08:40:00", 0, 5, 0],
        ]
    }
    scan_payload(payload, index)
    assert index.code_to_names["SMC"] == {"SEMARANG PONCOL"}
    assert index.name_to_codes["SEMARANG PONCOL"] == {"SMC"}


def test_non_station_rows_are_ignored():
    index = CodeNameIndex()
    payload = {
        "words": [
            [60, 100, 90, 113, "KRD", 0, 0, 0],
            [95, 100, 150, 113, "(KRD)", 0, 1, 0],
        ]
    }
    scan_payload(payload, index)
    assert index.pairs_found == 0


def test_code_conflict_is_reported_not_resolved():
    index = CodeNameIndex()
    index.code_to_names["XX"] = {"ALPHA", "BETA"}
    index.name_to_codes["ALPHA"] = {"XX"}
    index.name_to_codes["BETA"] = {"XX"}
    report = v3b_report(index)
    assert report["code_to_multiple_names"] == {"XX": ["ALPHA", "BETA"]}
    assert report["code_conflict_count"] == 1


def test_v3b_is_marked_non_circular():
    report = v3b_report(CodeNameIndex())
    assert report["circular"] is False
    assert report["rule"] == "V3b"


def test_edit_distance():
    assert _edit_distance("BATANG", "BATANG") == 0
    assert _edit_distance("BAGOR", "BOGOR") == 1
    assert _edit_distance("BATANG", "LAWANG") == 2


def test_near_duplicates_default_threshold_is_one():
    pairs = near_duplicates({"BAGOR", "BOGOR"})
    assert ("BAGOR", "BOGOR") in pairs


def test_prefix_pairs_find_truncations():
    pairs = prefix_pairs({"CIREBON", "CIREBON PRUJAKAN"})
    assert ("CIREBON", "CIREBON PRUJAKAN") in pairs


# --- index parser -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["249", "257F", "42-43", "233-234-235", "2724"],
)
def test_train_number_pattern_accepts_real_forms(text):
    assert TRAIN_NO_RE.match(text)


@pytest.mark.parametrize("text", ["SMC-BB", "PWT-TG-SLO", "KTG-SGU"])
def test_relation_pattern_accepts_real_forms(text):
    assert RELATION_RE.match(text)


def test_bands_separate_relation_from_class():
    row = [
        word(104, 100, "121"),
        word(142, 100, "249"),
        word(205, 100, "EKSEKUTIF"),
        word(243, 100, "CAMPURAN"),
        word(324, 100, "KALIGUNG"),
        word(399, 100, "SMC-BB"),
        word(449, 100, "08:40"),
        word(483, 100, "11:03"),
        word(521, 100, "464"),
    ]
    bands = _bands(row)
    assert [w.text for w in bands["relation"]] == ["SMC-BB"]
    assert [w.text for w in bands["printed_page"]] == ["464"]
    assert [w.text for w in bands["depart"]] == ["08:40"]
    assert [w.text for w in bands["arrive"]] == ["11:03"]


def test_parse_index_row_keeps_printed_page_out_of_arrive():
    row = [
        word(104, 100, "121"),
        word(142, 100, "249"),
        word(205, 100, "EKSEKUTIF"),
        word(243, 100, "CAMPURAN"),
        word(324, 100, "KALIGUNG"),
        word(399, 100, "SMC-BB"),
        word(449, 100, "08:40"),
        word(483, 100, "11:03"),
        word(521, 100, "464"),
    ]
    entry = parse_index_row(row, 56)
    assert entry is not None
    assert entry.arrive == "11:03"
    assert entry.printed_page == "464"
    assert entry.needs_review == []


def test_index_page_56_has_no_flags():
    path = FIXTURES / "page_0056.json"
    if not path.exists():
        pytest.skip("fixture missing")
    words = words_from_raw(json.loads(path.read_text()))
    entries = parse_index_pages({56: words})
    assert entries
    flagged = [e for e in entries if e.needs_review]
    assert flagged == []


# --- doctor -----------------------------------------------------------------


def test_doctor_reports_missing_raw_words(tmp_path):
    ok, detail = _check_raw_words(tmp_path)
    assert ok is False
    assert "make extract" in detail
