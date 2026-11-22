"""Tests for the T3 snap audit.

The audit exists because KDB sat at 5,208 m from rail while marked `accepted`.
It must surface every station above the warning threshold, including accepted
ones, so a future failure cannot hide.
"""

from __future__ import annotations

import pytest

from pipeline import snap_audit


def test_percentile_handles_small_and_empty_inputs():
    assert snap_audit.percentile([], 0.99) is None
    assert snap_audit.percentile([5.0], 0.99) == 5.0
    assert snap_audit.percentile([1.0, 2.0, 3.0], 0.5) == 2.0


def test_percentile_is_order_independent():
    values = [9.0, 1.0, 5.0, 3.0, 7.0]
    assert snap_audit.percentile(values, 0.99) == snap_audit.percentile(
        list(reversed(values)), 0.99
    )


@pytest.fixture(scope="module")
def report():
    try:
        return snap_audit.audit()
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"data not available: {error}")


def test_every_station_is_reported(report):
    assert len(report["rows"]) == report["stations_total"]
    assert report["stations_total"] > 0


def test_every_row_has_a_band(report):
    for row in report["rows"]:
        assert row["band"], row["code"]


def test_accepted_stations_above_threshold_are_listed(report):
    """An `accepted` coordinate above the threshold must appear in over_100m."""
    for row in report["rows"]:
        if (
            row["coord_status"] in ("accepted", "override")
            and row["snap_distance_m"] is not None
            and row["snap_distance_m"] > report["warn_threshold_m"]
        ):
            assert any(item["code"] == row["code"] for item in report["over_100m"]), row["code"]


def test_distribution_reports_a_maximum(report):
    assert report["distribution_m"]["max"] is not None
    assert report["distribution_m"]["max"] > 0


def test_missing_stations_have_no_snap(report):
    for row in report["missing"]:
        assert row["lat"] is None
