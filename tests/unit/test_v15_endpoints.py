"""Tests for the V15 endpoint cross-check (T2).

The comparison must be midnight-safe and must never auto-resolve a difference.
"""

from __future__ import annotations

from pipeline import v15_endpoints as v15


def test_circular_delta_is_midnight_safe():
    # 23:59:00 -> 00:01:00 is +2 minutes, not -23h58m.
    assert v15.circular_delta(60, 86340) == 120
    # and the reverse
    assert v15.circular_delta(86340, 60) == -120


def test_circular_delta_is_symmetric_in_magnitude():
    assert abs(v15.circular_delta(0, 3600)) == 3600
    assert abs(v15.circular_delta(3600, 0)) == 3600


def test_classify_boundaries():
    assert v15.classify(0) == "exact"
    assert v15.classify(60) == "within_1min"
    assert v15.classify(-60) == "within_1min"
    assert v15.classify(61) == "larger"
    assert v15.classify(-61) == "larger"
    assert v15.classify(None) == "missing"


def test_parse_hhmm_accepts_seconds():
    assert v15.parse_hhmm("08:15") == 8 * 3600 + 15 * 60
    assert v15.parse_hhmm("08:15:30") == 8 * 3600 + 15 * 60 + 30
    assert v15.parse_hhmm(None) is None
    assert v15.parse_hhmm("") is None
    assert v15.parse_hhmm("xx:yy") is None


def test_source_index_does_not_merge_duplicates():
    entries = [
        {"train_no": "1", "relation": "A-B", "depart": "08:00", "arrive": "09:00"},
        {"train_no": "1", "relation": "A-B", "depart": "10:00", "arrive": "11:00"},
    ]
    index, duplicates = v15.source_index(entries, "test")
    assert ("1", "A-B") in duplicates
    assert index[("1", "A-B")]["depart"] == "08:00"


def test_summarise_counts_every_comparison():
    results = [
        {
            "trip_id": "t1",
            "train_no": "1",
            "book": 1,
            "relation": "A-B",
            "sources": [
                {
                    "source": "test",
                    "status": "compared",
                    "page": 1,
                    "parsed_depart": "08:00:00",
                    "source_depart": "08:00",
                    "parsed_arrive": "09:05:00",
                    "source_arrive": "09:00",
                    "depart_delta_s": 0,
                    "arrive_delta_s": 300,
                    "depart_class": "exact",
                    "arrive_class": "larger",
                }
            ],
        }
    ]
    summary = v15.summarise(results)
    assert summary["per_source"]["test"]["exact"] == 1
    assert summary["per_source"]["test"]["larger"] == 1
    assert len(summary["larger"]) == 1


def test_absent_is_counted_not_hidden():
    results = [
        {
            "trip_id": "t1",
            "train_no": "9",
            "book": 2,
            "relation": "X-Y",
            "sources": [{"source": "test", "status": "absent", "page": None}],
        }
    ]
    summary = v15.summarise(results)
    assert summary["per_source"]["test"]["absent"] == 1
    assert len(summary["absent"]) == 1
