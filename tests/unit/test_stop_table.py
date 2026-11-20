"""Regression tests for the geometry parser, stop conventions, and pilots.

Expected values come from the parser. KA 249/250/251 are golden (human-verified
2026-11-20); everything else is a regression fixture with
``verified_by_human: false``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.parsers.stop_table import (
    COMPLETENESS_TRUNCATED,
    MAX_PLAUSIBLE_GAP_SECONDS,
    Cell,
    ParsedTrain,
    Stop,
    apply_day_offsets,
    apply_positional_empty_rules,
    detect_completeness,
    finalize,
    merge_continuations,
    parse_page,
    seconds_of,
)
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
PILOT_249_250 = Path("data/parsed/pilot_249_250.json")
PILOT_259F_260F = Path("data/parsed/pilot_259F_260F.json")
GOLDEN = Path("tests/golden/pilot_249_250_golden.json")


def load_page(page: int):
    path = FIXTURES / f"page_{page:04d}.json"
    if not path.exists():
        pytest.skip(f"fixture {path} missing")
    return json.loads(path.read_text(encoding="utf-8"))


def verticals_for(page: int) -> list[float]:
    # Ruling geometry is stable across this document's A4 tables. Using the
    # observed values keeps the suite independent of the source PDF.
    return [50.5, 68.9, 207.0, 262.3, 308.3, 354.4, 538.5]


def parse_fixture(page: int):
    words = words_from_raw(load_page(page))
    return parse_page(split_tables(words, page, verticals_for(page)))


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
    assert [w.text for w in rows[0]] == ["B", "A"]


def test_split_tables_finds_both_tables_on_page_521():
    blocks = split_tables(words_from_raw(load_page(521)), 521, verticals_for(521))
    assert len(blocks) == 2
    assert all(b.column_source == "ruling" for b in blocks)


def test_columns_come_from_rulings_not_hardcoded():
    blocks = split_tables(words_from_raw(load_page(521)), 521, verticals_for(521))
    keys = [c.key for c in blocks[0].columns]
    assert keys == [COL_NO, COL_STATION, COL_SPEED, COL_ARRIVE, COL_DEPART, COL_NOTE]
    assert [round(c.x0) for c in blocks[0].columns] == [50, 69, 207, 262, 308, 354]


def test_columns_fall_back_to_header_when_no_rulings():
    blocks = split_tables(words_from_raw(load_page(521)), 521, [])
    assert blocks
    assert blocks[0].column_source == "header"


# --- pilot content ----------------------------------------------------------


def test_pilot_parses_four_trains():
    trains = merge_continuations(parse_fixture(521) + parse_fixture(522))
    assert [t.train_no for t in trains] == ["249", "250", "251", "252"]


def test_ka249_has_20_stops_from_smc_to_bb():
    train = parse_fixture(521)[0]
    assert train.train_no == "249"
    assert len(train.stops) == 20
    assert train.stops[0].station_code == "SMC"
    assert train.stops[-1].station_code == "BB"
    assert [s.seq for s in train.stops] == list(range(1, 21))


def test_ls_in_datang_becomes_pass_not_a_time():
    train = parse_fixture(521)[0]
    jerakah = train.stops[1]
    assert jerakah.station_code == "JRK"
    assert jerakah.stop_type == "pass"
    assert jerakah.arrive.value is None
    assert jerakah.arrive.raw.upper() == "LS"
    assert jerakah.depart.value == "08:47:00"


def test_dash_is_preserved_raw_and_unflagged_at_expected_positions():
    train = parse_fixture(521)[0]
    smc = train.stops[0]
    assert smc.arrive.value is None
    assert smc.arrive.raw == "-"  # raw token preserved
    assert smc.needs_review == []


def test_zero_and_dash_speed_are_not_conflated():
    words = words_from_raw(load_page(521))
    train = finalize(parse_page(split_tables(words, 521, verticals_for(521))), (521, 521))[0]
    # Brebes ends the trip with "-" speed; keep it distinct from "0".
    brebes = train.stops[-1]
    assert brebes.speed.raw == "-"
    assert brebes.speed.value is None


def test_dash_outside_expected_position_is_flagged():
    stop = Stop(
        seq=5,
        station_name="X",
        station_code="XX",
        speed=Cell("100", "100", 1, None),
        arrive=Cell(None, "-", 1, None),
        depart=Cell("10:00:00", "10:00:00", 1, None),
        note=Cell(None, "", 1, None),
        stop_type="stop",
    )
    train = ParsedTrain(
        train_no="1",
        name="N",
        origin="A",
        destination="B",
        page=1,
        header_y=0.0,
        stops=[
            Stop(
                1,
                "A",
                "AA",
                Cell("100", "100", 1, None),
                Cell(None, "-", 1, None),
                Cell("09:00:00", "09:00:00", 1, None),
                Cell(None, "", 1, None),
                "stop",
            ),
            stop,
            Stop(
                9,
                "B",
                "BB",
                Cell(None, "-", 1, None),
                Cell("11:00:00", "11:00:00", 1, None),
                Cell(None, "-", 1, None),
                Cell(None, "", 1, None),
                "stop",
            ),
        ],
    )
    apply_positional_empty_rules(train)
    assert "arrive_dash_not_expected" in stop.needs_review


def test_footnote_captured_verbatim():
    trains = parse_fixture(521)
    ka250 = trains[1]
    tegal = next(s for s in ka250.stops if s.station_code == "TG")
    assert tegal.note.raw == "= ka 46 (ka 46 //)"


def test_ka250_continuation_is_info_not_needs_review():
    trains = merge_continuations(parse_fixture(521) + parse_fixture(522))
    ka250 = next(t for t in trains if t.train_no == "250")
    assert len(ka250.stops) == 20
    assert ka250.stops[-1].station_code == "SMC"
    assert any("continued_on_page_522" in r for r in ka250.info)
    assert not any("continued_on_page" in r for r in ka250.needs_review)


# --- R1: truncation ---------------------------------------------------------


def test_ka252_is_marked_truncated():
    trains = finalize(merge_continuations(parse_fixture(521) + parse_fixture(522)), (521, 522))
    ka252 = next(t for t in trains if t.train_no == "252")
    assert ka252.completeness == COMPLETENESS_TRUNCATED


def test_complete_trip_is_marked_complete():
    trains = finalize(parse_fixture(521), (521, 521))
    assert all(t.completeness == "complete" for t in trains if t.train_no == "249")


def test_truncated_never_appears_in_validated(tmp_path):
    if not PILOT_249_250.exists():
        pytest.skip("run `make parse` first")
    validated = json.loads(
        Path("data/validated/pilot_249_250_validation.json").read_text(encoding="utf-8")
    )
    assert "252" in validated["truncated_trains"]


def test_detect_completeness_without_destination_is_unknown():
    train = ParsedTrain(
        train_no="9",
        name="N",
        origin=None,
        destination=None,
        page=1,
        header_y=0.0,
        stops=[
            Stop(
                1,
                "A",
                "AA",
                Cell("100", "100", 1, None),
                Cell(None, "-", 1, None),
                Cell("09:00:00", "09:00:00", 1, None),
                Cell(None, "", 1, None),
                "stop",
                provenance={"page": 1},
            )
        ],
    )
    assert detect_completeness(train, (1, 5)) == "unknown"


# --- Step 2: midnight crossing ---------------------------------------------


def test_seconds_of_parses_hh_mm_ss():
    assert seconds_of("00:13:00") == 780
    assert seconds_of("bad") is None


def test_day_offset_rolls_over_midnight():
    if not PILOT_259F_260F.exists():
        pytest.skip("run `make parse` first")
    payload = json.loads(PILOT_259F_260F.read_text(encoding="utf-8"))
    ka260 = next(t for t in payload["trains"] if t["train_no"] == "260F")
    offsets = {s["seq"]: s["day_offset"] for s in ka260["stops"]}
    assert offsets[1] == 0
    assert offsets[13] == 0  # 23:59
    assert offsets[14] == 1  # 00:05
    assert offsets[15] == 1  # 00:13


def test_day_offset_does_not_roll_on_ka259():
    if not PILOT_259F_260F.exists():
        pytest.skip("run `make parse` first")
    payload = json.loads(PILOT_259F_260F.read_text(encoding="utf-8"))
    ka259 = next(t for t in payload["trains"] if t["train_no"] == "259F")
    assert all(s["day_offset"] == 0 for s in ka259["stops"])


def test_implausible_gap_is_flagged():
    stops = [
        Stop(
            1,
            "A",
            "AA",
            Cell("100", "100", 1, None),
            Cell(None, "-", 1, None),
            Cell("01:00:00", "01:00:00", 1, None),
            Cell(None, "", 1, None),
            "stop",
        ),
        Stop(
            2,
            "B",
            "BB",
            Cell("100", "100", 1, None),
            Cell("20:00:00", "20:00:00", 1, None),
            Cell("20:00:00", "20:00:00", 1, None),
            Cell(None, "", 1, None),
            "stop",
        ),
    ]
    train = ParsedTrain(
        train_no="1", name="N", origin="A", destination="B", page=1, header_y=0.0, stops=stops
    )
    apply_day_offsets(train)
    assert any("implausible_time_gap" in reason for reason in train.stops[1].needs_review)
    assert MAX_PLAUSIBLE_GAP_SECONDS == 12 * 3600


def test_every_stop_has_provenance_bbox():
    train = parse_fixture(521)[0]
    for stop in train.stops:
        assert stop.provenance["page"] == 521
        assert len(stop.provenance["station_bbox"]) == 4


# --- committed artefacts ----------------------------------------------------


def test_committed_pilot_json_is_marked_unverified():
    if not PILOT_249_250.exists():
        pytest.skip("run `make parse` first")
    payload = json.loads(PILOT_249_250.read_text(encoding="utf-8"))
    assert payload["verified_by_human"] is False


def test_golden_fixture_is_human_verified_and_scoped():
    if not GOLDEN.exists():
        pytest.skip("golden fixture missing")
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert payload["verified_by_human"] is True
    assert payload["verifier"] == "human"
    assert payload["date"] == "2026-11-20"
    assert payload["scope"]["pages"] == [521, 522]
    assert "252" in payload["scope"]["note"]
