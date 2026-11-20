"""Regression tests for the two Book 2 parser defects (D2).

Both defects were found while parsing Book 2 and fixed generically. These tests
pin the behaviour using a single real page fixture (``page_0771.json``, words
only, never the PDF):

1. a station name wrapped across three row bands
   ("Yogyakarta / International / Airport (YIA)");
2. multi-line cell reading order — a cell's words must be read top-down before
   left-to-right, otherwise the lines interleave.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.parsers.stop_table import parse_page
from pipeline.parsers.table_geometry import Word, group_rows, split_tables, words_from_raw

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAGE = 771
RULINGS = [50.5, 68.9, 207.0, 262.3, 308.3, 354.4, 538.5]


def load_words():
    path = FIXTURES / f"page_{PAGE:04d}.json"
    if not path.exists():
        pytest.skip(f"fixture {path} missing")
    return words_from_raw(json.loads(path.read_text(encoding="utf-8")))


def parse():
    return parse_page(split_tables(load_words(), PAGE, RULINGS))


# --- defect 1: wrapped station name ----------------------------------------


def test_three_line_station_name_is_one_row_not_three():
    """The name spans three printed lines above/around its sequence number."""
    trains = parse()
    ka541 = next(t for t in trains if t.train_no == "541")
    assert len(ka541.stops) == 7

    last = ka541.stops[-1]
    assert last.seq == 7
    assert last.station_code == "YIA"
    assert last.station_name == "Yogyakarta International Airport"


def test_wrapped_name_words_are_attached_to_the_nearest_sequence_anchor():
    """Word-level: all three name fragments belong to the seq-7 row."""
    blocks = split_tables(load_words(), PAGE, RULINGS)
    # The last table on this page holds KA 544 (YIA -> YK); its single row on
    # this page has a three-line station name above and around its seq "1".
    block = blocks[-1]
    row = next(r for r in block.rows if any(w.text.strip() == "1" for w in r))
    texts = {w.text for w in row}
    assert {"Yogyakarta", "International", "Airport", "(YIA)"} <= texts


def test_no_station_name_is_left_behind_in_its_own_row():
    """A wrapped name must not produce extra rows that look like stops."""
    trains = parse()
    for train in trains:
        for stop in train.stops:
            # Every parsed stop must have a sequence number; a fragment row would
            # have none and be dropped, silently losing the name.
            assert stop.seq is not None
            assert stop.station_code is not None, (
                f"KA {train.train_no} seq {stop.seq} lost its station code"
            )


# --- defect 2: multi-line cell reading order --------------------------------


def test_cell_words_are_joined_top_down_then_left_to_right():
    """Directly pin the reading-order rule that the defect violated."""
    from pipeline.parsers.stop_table import _join

    # Simulate "Yogyakarta" (y=731), "International" (y=731),
    # "Airport" (y=745), "(YIA)" (y=745) as the parser sees them.
    words = [
        Word(x0=72, y0=731, x1=122, y1=738, text="Yogyakarta", block=0, line=0, word=0),
        Word(x0=122, y0=731, x1=200, y1=738, text="International", block=0, line=0, word=1),
        Word(x0=72, y0=745, x1=104, y1=752, text="Airport", block=0, line=1, word=0),
        Word(x0=104, y0=745, x1=140, y1=752, text="(YIA)", block=0, line=1, word=1),
    ]
    assert _join(words) == "Yogyakarta International Airport (YIA)"


def test_left_to_right_join_would_interleave_lines():
    """Counter-example: a pure x-sort produces the wrong name, proving the rule."""
    words = [
        Word(x0=72, y0=731, x1=122, y1=738, text="Yogyakarta", block=0, line=0, word=0),
        Word(x0=122, y0=731, x1=200, y1=738, text="International", block=0, line=0, word=1),
        Word(x0=72, y0=745, x1=104, y1=752, text="Airport", block=0, line=1, word=0),
        Word(x0=104, y0=745, x1=140, y1=752, text="(YIA)", block=0, line=1, word=1),
    ]
    by_x = " ".join(w.text for w in sorted(words, key=lambda w: w.x0))
    assert by_x != "Yogyakarta International Airport (YIA)"


# --- the two defects jointly ------------------------------------------------


def test_both_directions_of_the_airport_trip_parse_fully():
    """YK->YIA and YIA->YK both start and end at the right stations."""
    trains = {t.train_no: t for t in parse() if t.train_no}
    yk_to_yia = trains["541"]
    yia_to_yk = trains["542"]

    assert yk_to_yia.stops[0].station_code == "YK"
    assert yk_to_yia.stops[-1].station_code == "YIA"
    assert yia_to_yk.stops[0].station_code == "YIA"
    assert yia_to_yk.stops[-1].station_code == "YK"


def test_group_rows_without_anchor_still_works():
    """The fallback path (no No. column) must not regress."""
    rows = group_rows(
        [
            Word(x0=10, y0=10, x1=20, y1=20, text="A", block=0, line=0, word=0),
            Word(x0=10, y0=10, x1=20, y1=20, text="B", block=0, line=0, word=1),
            Word(x0=10, y0=40, x1=20, y1=50, text="C", block=0, line=1, word=0),
        ]
    )
    assert [len(r) for r in rows] == [2, 1]
