"""Tests for human conflict resolutions (H8) and rule-approved confirmations (H9).

A name conflict is resolved only by a recorded human decision. The report must
show that decision next to the evidence, and must never silently drop the
conflict from the list.
"""

from __future__ import annotations

from pipeline import station_aliases as sa


def test_karangsari_codes_are_distinct_stations():
    stations = sa.load()
    assert "KRAI" in stations
    assert "KRR" in stations
    assert stations["KRAI"]["official_name"] == "Karangsari"
    assert stations["KRR"]["official_name"] == "Karangsari"
    # The disambiguator is what makes them distinguishable in the UI.
    assert stations["KRAI"]["disambiguator"] == "Garut"
    assert stations["KRR"]["disambiguator"] == "Banyumas"


def test_conflict_resolutions_are_recorded(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        """
stations:
  AAA:
    official_name: "Same"
    station_kind: passenger
conflict_resolutions:
  SAME NAME:
    codes: ["AAA", "BBB"]
    resolution: "two distinct stations"
    decided_by: "human"
    date: "2026-11-22"
""",
        encoding="utf-8",
    )
    resolutions = sa.load_resolutions(path)
    assert "SAME NAME" in resolutions
    assert resolutions["SAME NAME"]["resolution"] == "two distinct stations"
    assert resolutions["SAME NAME"]["decided_by"] == "human"


def test_missing_resolutions_file_is_not_an_error(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text('stations:\n  AAA:\n    official_name: "A"\n', encoding="utf-8")
    assert sa.load_resolutions(path) == {}


def test_disambiguator_survives_loading(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        """
stations:
  KRAI:
    official_name: "Karangsari"
    disambiguator: "Garut"
    station_kind: passenger
""",
        encoding="utf-8",
    )
    stations = sa.load(path)
    assert stations["KRAI"]["disambiguator"] == "Garut"
