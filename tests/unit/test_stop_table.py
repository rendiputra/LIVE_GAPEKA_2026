"""Regression tests for the geometry parser and the pilot output.

These are **regression** tests, not golden tests: the expected values come from
the parser and are marked ``verified_by_human: false`` until a human confirms the
rows against the PDF.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.parsers.stop_table import merge_continuations, parse_page
from pipeline.parsers.table_geometry import (
    COL_ARRIVE,
    COL_DEPART,
    COL_NO,
    COL_NOTE,
    COL_SPEED,
    COL_STATION,
    group_rows,
    split_tables,
    words_from_raw,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
PILOT = Path("data/parsed/pilot_249_250.json")


def load_page(page: int):
    path = FIXTURES / f"page_{page:04d}.json"
    if not path.exists():
        pytest.skip(f"fixture {path} missing")
    return json.loads(path.read_text(encoding="utf-8"))


def verticals_for(page: int) -> list[float]:
    # Ruling geometry is stable across this document's A4 tables. The test uses
    # the values observed on the fixture rather than re-opening the PDF, so the
    # suite never needs the source document.
    return [50.5, 68.9, 207.0, 262.3, 308.3, 354.4, 538.5]


# --- geometry ---------------------------------------------------------------


def test_words_from_raw_preserves_bbox():
    payload = {"words": [[1.0, 2.0, 3.0, 4.0, "TXT", 0, 0, 0]]}
    word = words_from_raw(payload)[0]
    assert word.text == "TXT"
    assert word.bbox() == [1.0, 2.0, 3.0, 4.0]


def test_group_rows_splits_on_y():
    payload = {
        "words": [
            [0, 10, 10, 20, "B", 0, 0, 0],
            [0, 10, 10, 20, "A", 0, 0, 1],
            [0, 30, 10, 40, "C", 0, 0, 2],
        ]
    }
    rows = group_rows(words_from_raw(payload))
    assert [len(r) for r in rows] == [2, 1]
    assert [w.text for w in rows[0]] == ["B", "A"]  # x order


def test_split_tables_finds_both_tables_on_page_521():
    words = words_from_raw(load_page(521))
    blocks = split_tables(words, 521, verticals_for(521))
    assert len(blocks) == 2
    assert all(b.column_source == "ruling" for b in blocks)


def test_columns_come_from_rulings_not_hardcoded():
    words = words_from_raw(load_page(521))
    blocks = split_tables(words, 521, verticals_for(521))
    keys = [c.key for c in blocks[0].columns]
    assert keys == [COL_NO, COL_STATION, COL_SPEED, COL_ARRIVE, COL_DEPART, COL_NOTE]
    assert [round(c.x0) for c in blocks[0].columns] == [50, 69, 207, 262, 308, 354]


def test_columns_fall_back_to_header_when_no_rulings():
    words = words_from_raw(load_page(521))
    blocks = split_tables(words, 521, [])
    assert blocks, "fallback must still produce tables"
    assert blocks[0].column_source == "header"


# --- pilot content ----------------------------------------------------------


def test_pilot_parses_four_trains():
    words_521 = words_from_raw(load_page(521))
    words_522 = words_from_raw(load_page(522))
    trains = parse_page(split_tables(words_521, 521, verticals_for(521)))
    trains += parse_page(split_tables(words_522, 522, verticals_for(522)))
    trains = merge_continuations(trains)
    assert [t.train_no for t in trains] == ["249", "250", "251", "252"]


def test_ka249_has_20_stops_from_smc_to_bb():
    words = words_from_raw(load_page(521))
    train = parse_page(split_tables(words, 521, verticals_for(521)))[0]
    assert train.train_no == "249"
    assert len(train.stops) == 20
    assert train.stops[0].station_code == "SMC"
    assert train.stops[-1].station_code == "BB"
    assert [s.seq for s in train.stops] == list(range(1, 21))


def test_ls_in_datang_becomes_pass_not_a_time():
    words = words_from_raw(load_page(521))
    train = parse_page(split_tables(words, 521, verticals_for(521)))[0]
    jerakah = train.stops[1]
    assert jerakah.station_code == "JRK"
    assert jerakah.stop_type == "pass"
    assert jerakah.arrive.value is None
    assert jerakah.arrive.raw.upper() == "LS"
    assert jerakah.depart.value == "08:47:00"


def test_dash_is_null_without_needs_review():
    words = words_from_raw(load_page(521))
    train = parse_page(split_tables(words, 521, verticals_for(521)))[0]
    smc = train.stops[0]
    assert smc.arrive.value is None
    assert smc.arrive.raw == "-"
    assert smc.needs_review == []


def test_missing_speed_at_brebes_is_flagged():
    words = words_from_raw(load_page(521))
    train = parse_page(split_tables(words, 521, verticals_for(521)))[0]
    brebes = train.stops[-1]
    assert brebes.station_code == "BB"
    assert brebes.speed.raw == "-"
    # "-" is the document's explicit empty marker, so it is null without review.
    assert brebes.needs_review == []


def test_footnote_captured_verbatim():
    words = words_from_raw(load_page(521))
    trains = parse_page(split_tables(words, 521, verticals_for(521)))
    ka250 = trains[1]
    tegal = next(s for s in ka250.stops if s.station_code == "TG")
    assert "ka 46" in tegal.note.raw
    assert tegal.note.raw == "= ka 46 (ka 46 //)"


def test_ka250_continues_onto_page_522():
    trains_521 = parse_page(split_tables(words_from_raw(load_page(521)), 521, verticals_for(521)))
    trains_522 = parse_page(split_tables(words_from_raw(load_page(522)), 522, verticals_for(522)))
    merged = merge_continuations(trains_521 + trains_522)
    ka250 = next(t for t in merged if t.train_no == "250")
    assert len(ka250.stops) == 20
    assert ka250.stops[-1].seq == 20
    assert ka250.stops[-1].station_code == "SMC"
    assert any("continued_on_page_522" in r for r in ka250.needs_review)


def test_every_stop_has_provenance_bbox():
    words = words_from_raw(load_page(521))
    train = parse_page(split_tables(words, 521, verticals_for(521)))[0]
    for stop in train.stops:
        assert stop.provenance["page"] == 521
        assert stop.provenance["station_bbox"] is not None
        assert len(stop.provenance["station_bbox"]) == 4


# --- committed artefact -----------------------------------------------------


def test_committed_pilot_json_is_marked_unverified():
    if not PILOT.exists():
        pytest.skip("run `make parse` first")
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    assert payload["verified_by_human"] is False
    assert len(payload["trains"]) == 4
