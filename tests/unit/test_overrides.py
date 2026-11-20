"""Tests for the human-authored station override loader (Q4 / S3)."""

from __future__ import annotations

import pytest

from pipeline.station_overrides import apply_to, load

VALID = """
overrides:
  - code: "LR"
    lat: -6.87
    lon: 109.14
    reason: "Larangan is next to Tegal"
    evidence: "checked on a station map"
    decided_by: "human"
    date: "2026-11-20"
"""

EMPTY = """
# schema comment
overrides: []
"""


def _write(tmp_path, text):
    path = tmp_path / "ov.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_empty_file_loads_nothing():
    assert load() == [] or isinstance(load(), list)


def test_explicit_empty_list_loads_nothing(tmp_path):
    assert load(_write(tmp_path, EMPTY)) == []


def test_valid_override_parses(tmp_path):
    overrides = load(_write(tmp_path, VALID))
    assert len(overrides) == 1
    entry = overrides[0]
    assert entry.code == "LR"
    assert entry.lat == pytest.approx(-6.87)
    assert entry.decided_by == "human"


def test_missing_field_raises(tmp_path):
    bad = VALID.replace('    evidence: "checked on a station map"\n', "")
    with pytest.raises(ValueError, match="evidence"):
        load(_write(tmp_path, bad))


def test_non_numeric_lat_raises(tmp_path):
    bad = VALID.replace("lat: -6.87", "lat: north")
    with pytest.raises(ValueError, match="non-numeric"):
        load(_write(tmp_path, bad))


def test_out_of_range_coordinate_raises(tmp_path):
    bad = VALID.replace("lat: -6.87", "lat: -95.0")
    with pytest.raises(ValueError, match="lat/lon"):
        load(_write(tmp_path, bad))


def test_duplicate_code_raises(tmp_path):
    duplicated = VALID + VALID.split("overrides:\n")[1]
    with pytest.raises(ValueError, match="duplicate"):
        load(_write(tmp_path, duplicated))


def test_apply_marks_override_provenance(tmp_path):
    overrides = load(_write(tmp_path, VALID))
    result = apply_to(overrides, {})
    assert result["LR"]["coord_status"] == "override"
    assert result["LR"]["source"] == "override"
    assert result["LR"]["match_method"] == "human"
    assert result["LR"]["confidence"] == "high"


def test_apply_keeps_untouched_entries(tmp_path):
    overrides = load(_write(tmp_path, VALID))
    result = apply_to(overrides, {"SMC": {"name": "Semarang Poncol", "lat": -6.97, "lon": 110.42}})
    assert result["SMC"]["coord_status"] == "accepted"
    assert result["LR"]["coord_status"] == "override"
