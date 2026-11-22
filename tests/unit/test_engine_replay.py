"""Regression tests for the replay generator (F-a).

The original bug: the replay looped ``range(0, 86400)`` and called the private
``_position_for`` with a single service-date elapsed. Every trip that crossed
midnight was cut at 23:59:30, so KA 260F had no 00:00-00:13 frames and the
previous-service-date tail was invisible.

These tests pin the engine behaviour the fixed generator relies on, plus the
window itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from engine.model import Policy
from engine.position import positions_at

WIB = ZoneInfo("Asia/Jakarta")


@pytest.fixture(scope="module")
def snapshot():
    from engine.snapshot import load

    try:
        return load()
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")


def at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 12, day, hour, minute, tzinfo=WIB)


def test_window_is_longer_than_one_service_date():
    """A 24 h window is the bug; the generator must cover the tails."""
    from pipeline import engine_replay

    assert engine_replay.WINDOW_HOURS == 30
    assert engine_replay.STEP_S == 30


def test_260f_tail_of_previous_service_date_is_visible(snapshot):
    """At 2026-12-01 00:05 the run that started on 2026-11-30 is still going."""
    positions = positions_at(snapshot, at(1, 0, 5), Policy(show_fakultatif=True))
    matches = [p for p in positions if p.train_no == "260F"]
    assert matches, "previous-service-date tail of KA 260F is missing"
    assert matches[0].s_m > 0


def test_260f_tail_of_its_own_service_date_is_visible(snapshot):
    """At 2026-12-02 00:05 the run that started on 2026-12-01 is still going."""
    positions = positions_at(snapshot, at(2, 0, 5), Policy(show_fakultatif=True))
    matches = [p for p in positions if p.train_no == "260F"]
    assert matches, "own-service-date tail of KA 260F is missing"
    assert matches[0].s_m > 0


def test_260f_is_absent_before_its_first_departure(snapshot):
    """Negative case: the fix must not make the trip appear all day."""
    positions = positions_at(snapshot, at(2, 12, 0), Policy(show_fakultatif=True))
    assert not [p for p in positions if p.train_no == "260F"]


def test_last_frame_clock_is_30_hours_after_the_first():
    from pipeline.engine_replay import START_DATE, WINDOW_HOURS

    start = datetime(START_DATE.year, START_DATE.month, START_DATE.day, tzinfo=WIB)
    end = start + timedelta(hours=WINDOW_HOURS)
    assert end.isoformat() == "2026-12-02T06:00:00+07:00"
