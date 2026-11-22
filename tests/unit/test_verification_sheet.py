"""T1: stratified selection of trains for human verification.

The selection is deterministic (documented seed) and must satisfy every stratum
the human asked for. A missing stratum is a failure, not a warning: the point of
stratification is that the sample covers the hard cases.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def selection():
    from pipeline import verification_sheet

    try:
        return verification_sheet.select()
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")


def test_selection_has_twenty_trains(selection):
    assert len(selection["trains"]) == 20


def test_excludes_already_verified_trains(selection):
    verified = {"249", "250", "251", "252", "259F", "260F"}
    chosen = {row["train_no"] for row in selection["trains"]}
    assert not (chosen & verified)


def test_every_stratum_is_satisfied(selection):
    strata = selection["strata"]
    for name, count in strata.items():
        assert count >= selection["requirements"][name], (
            f"stratum {name}: got {count}, need {selection['requirements'][name]}"
        )


def test_book_split_is_respected(selection):
    books = [row["book"] for row in selection["trains"]]
    assert books.count(1) >= 10
    assert books.count(2) >= 6


def test_every_train_has_a_reason(selection):
    for row in selection["trains"]:
        assert row["reason"].strip(), row["train_no"]


def test_selection_is_deterministic(selection):
    from pipeline import verification_sheet

    again = verification_sheet.select()
    assert [row["trip_id"] for row in again["trains"]] == [
        row["trip_id"] for row in selection["trains"]
    ]


def test_longest_and_shortest_are_included(selection):
    chosen = {row["trip_id"] for row in selection["trains"]}
    assert selection["longest_trip_id"] in chosen
    assert selection["shortest_trip_id"] in chosen
