"""Tests for Phase 5c mechanisms (written before the implementation).

Covers:
- P1: rule-approved override provenance
- P2: tracked-config hash
- Q1(a): snap pins
- Q3: arrive/depart day offsets for a midnight-straddling stop
"""

from __future__ import annotations

# --- P1: provenance ---------------------------------------------------------


def test_human_override_keeps_human_provenance(tmp_path):
    from pipeline import station_overrides as so

    path = tmp_path / "overrides.yaml"
    path.write_text(
        "overrides:\n"
        '  - code: "ABC"\n'
        "    lat: -6.5\n"
        "    lon: 107.0\n"
        '    reason: "r"\n'
        '    evidence: "e"\n'
        '    decided_by: "human"\n'
        '    date: "2026-11-22"\n',
        encoding="utf-8",
    )
    overrides = so.load(path)
    assert len(overrides) == 1
    assert overrides[0].provenance == "human_override"


def test_rule_override_is_marked_override_rule_approved(tmp_path):
    from pipeline import station_overrides as so

    path = tmp_path / "overrides.yaml"
    path.write_text(
        "overrides:\n"
        '  - code: "ABC"\n'
        "    lat: -6.5\n"
        "    lon: 107.0\n"
        '    reason: "rule H6"\n'
        '    evidence: "gate"\n'
        '    decided_by: "rule:H6"\n'
        '    date: "2026-11-22"\n',
        encoding="utf-8",
    )
    overrides = so.load(path)
    assert overrides[0].provenance == "override_rule_approved"
    assert overrides[0].decided_by == "rule:H6"


def test_apply_to_records_provenance(tmp_path):
    from pipeline import station_overrides as so

    path = tmp_path / "overrides.yaml"
    path.write_text(
        "overrides:\n"
        '  - code: "ABC"\n'
        "    lat: -6.5\n"
        "    lon: 107.0\n"
        '    reason: "rule H6"\n'
        '    evidence: "gate"\n'
        '    decided_by: "rule:H6"\n'
        '    date: "2026-11-22"\n',
        encoding="utf-8",
    )
    applied = so.apply_to(so.load(path), {})
    assert applied["ABC"]["coord_provenance"] == "override_rule_approved"
    assert applied["ABC"]["coord_status"] == "override"


# --- P2: tracked config hash ------------------------------------------------


def test_config_hash_is_deterministic_and_changes_with_content(tmp_path):
    from pipeline import config_tracking

    (tmp_path / "a.yaml").write_text("x: 1\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("y: 2\n", encoding="utf-8")

    first = config_tracking.hash_paths([tmp_path / "a.yaml", tmp_path / "b.yaml"])
    second = config_tracking.hash_paths([tmp_path / "b.yaml", tmp_path / "a.yaml"])
    assert first == second  # order independent

    (tmp_path / "b.yaml").write_text("y: 3\n", encoding="utf-8")
    third = config_tracking.hash_paths([tmp_path / "a.yaml", tmp_path / "b.yaml"])
    assert third != first


def test_config_hash_ignores_missing_files(tmp_path):
    from pipeline import config_tracking

    (tmp_path / "a.yaml").write_text("x: 1\n", encoding="utf-8")
    assert config_tracking.hash_paths(
        [tmp_path / "a.yaml", tmp_path / "missing.yaml"]
    ) == config_tracking.hash_paths([tmp_path / "a.yaml"])


# --- Q1(a): snap pins -------------------------------------------------------


def test_snap_pins_parse_the_schema(tmp_path):
    from pipeline import snap_pins

    path = tmp_path / "snap_pins.yaml"
    path.write_text(
        "pins:\n"
        '  - station: "TLM"\n'
        "    way_id: 1311188691\n"
        '    reason: "triple 1.000 vs 1.794"\n'
        '    evidence: "data/review/h5_h6_gate.json"\n'
        '    decided_by: "human"\n'
        '    date: "2026-11-22"\n',
        encoding="utf-8",
    )
    pins = snap_pins.load(path)
    assert len(pins) == 1
    assert pins[0].station == "TLM"
    assert pins[0].way_id == 1311188691

    index = snap_pins.index(pins)
    assert index["TLM"].way_id == 1311188691


# --- Q3: midnight-straddling day offsets -----------------------------------


def test_line_day_offsets_splits_a_midnight_dwell():
    from pipeline.day_offsets import derive

    # arrive 23:58, depart 00:03 -> arrival on day N, departure on day N+1.
    arrive, depart = derive("23:58:00", "00:03:00", 1)
    assert arrive == 0
    assert depart == 1


def test_line_day_offsets_keeps_a_normal_row():
    from pipeline.day_offsets import derive

    arrive, depart = derive("23:10:00", "23:14:00", 0)
    assert arrive == 0
    assert depart == 0


def test_line_day_offsets_handles_a_pass_row():
    from pipeline.day_offsets import derive

    # pass rows have one printed time; day offset is shared
    arrive, depart = derive("00:05:00", None, 1)
    assert arrive == 1
    assert depart == 1


def test_line_day_offsets_flags_a_long_dwell():
    from pipeline.day_offsets import dwell_minutes, is_long_dwell

    minutes = dwell_minutes("23:00:00", "00:30:00", 1)
    assert minutes == 90
    assert is_long_dwell(minutes) is True
    assert is_long_dwell(30) is False


# --- Q3: V1 uses absolute times -------------------------------------------


def test_absolute_times_put_the_arrival_on_the_previous_day():
    from pipeline.day_offsets import absolute_times

    arrive, depart = absolute_times("23:58:00", "00:03:00", 1)
    assert arrive == 23 * 3600 + 58 * 60  # day 0
    assert depart == 86400 + 3 * 60  # day 1


def test_absolute_times_keeps_a_normal_row_on_one_day():
    from pipeline.day_offsets import absolute_times

    arrive, depart = absolute_times("23:10:00", "23:14:00", 0)
    assert arrive == 23 * 3600 + 10 * 60
    assert depart == 23 * 3600 + 14 * 60


def test_v1_accepts_a_midnight_straddling_stop():
    """A stop that arrives 23:58 and departs 00:03 must not be a V1 violation."""
    from pipeline.parsers.stop_table import ParsedTrain, Stop
    from pipeline.validators import validate_v1

    def stop(seq, code, arrive, depart, day_offset):
        return Stop(
            seq=seq,
            station_code=code,
            station_name=code,
            arrive=_cell(arrive),
            depart=_cell(depart),
            day_offset=day_offset,
            stop_type="stop",
            speed=_cell("0"),
            note=_cell(""),
            provenance={"page": 1},
        )

    train = ParsedTrain(
        train_no="9999",
        name=None,
        origin="AAA",
        destination="CCC",
        page=1,
        header_y=0.0,
        stops=[
            stop(1, "AAA", "23:40:00", "23:40:00", 0),
            stop(2, "BBB", "23:58:00", "00:03:00", 1),
            stop(3, "CCC", "00:20:00", "00:20:00", 1),
        ],
    )
    report = validate_v1([train])
    assert report.violations == []
    assert report.checked == 3


def test_v1_flags_a_real_backwards_time():
    from pipeline.parsers.stop_table import ParsedTrain, Stop
    from pipeline.validators import validate_v1

    def stop(seq, code, arrive, depart, day_offset):
        return Stop(
            seq=seq,
            station_code=code,
            station_name=code,
            arrive=_cell(arrive),
            depart=_cell(depart),
            day_offset=day_offset,
            stop_type="stop",
            speed=_cell("0"),
            note=_cell(""),
            provenance={"page": 1},
        )

    train = ParsedTrain(
        train_no="9998",
        name=None,
        origin="AAA",
        destination="BBB",
        page=1,
        header_y=0.0,
        stops=[
            stop(1, "AAA", "10:00:00", "10:00:00", 0),
            stop(2, "BBB", "09:00:00", "09:00:00", 0),
        ],
    )
    report = validate_v1([train])
    assert len(report.violations) == 1


def _cell(value):
    """Build a parsed cell the way the parser does."""
    from pipeline.parsers.stop_table import Cell

    return Cell(
        value=value,
        raw=value or "",
        source="printed" if value else "empty",
        page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
    )


# --- H9: human confirmation of a rule-approved coordinate ------------------


def test_human_confirmed_flag_is_parsed(tmp_path):
    from pipeline import station_overrides as so

    path = tmp_path / "overrides.yaml"
    path.write_text(
        "overrides:\n"
        '  - code: "ABC"\n'
        "    lat: -6.5\n"
        "    lon: 107.0\n"
        '    reason: "rule"\n'
        '    evidence: "gate"\n'
        '    decided_by: "rule:H6"\n'
        '    date: "2026-11-22"\n'
        "    human_confirmed: true\n",
        encoding="utf-8",
    )
    overrides = so.load(path)
    assert overrides[0].human_confirmed is True
    applied = so.apply_to(overrides, {})
    assert applied["ABC"]["human_confirmed"] is True
    # Confirmation does not change the provenance.
    assert applied["ABC"]["coord_provenance"] == "override_rule_approved"


def test_human_confirmed_defaults_to_false(tmp_path):
    from pipeline import station_overrides as so

    path = tmp_path / "overrides.yaml"
    path.write_text(
        "overrides:\n"
        '  - code: "ABC"\n'
        "    lat: -6.5\n"
        "    lon: 107.0\n"
        '    reason: "r"\n'
        '    evidence: "e"\n'
        '    decided_by: "human"\n'
        '    date: "2026-11-22"\n',
        encoding="utf-8",
    )
    assert so.load(path)[0].human_confirmed is False
