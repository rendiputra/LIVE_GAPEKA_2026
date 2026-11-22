"""Tests for the human segment-review mechanism (ADR 005).

Both decisions must be pinned: ``accept_route`` turns a suspect segment into
``osm_routed_reviewed`` (counted as complete), ``needs_bridge`` leaves it
suspect. A review on a non-suspect segment must be ignored, not silently obeyed.
"""

from __future__ import annotations

from pipeline import segment_reviews as sr


def review(decision: str, from_code: str = "A", to_code: str = "B") -> sr.Review:
    return sr.Review(
        from_code=from_code,
        to_code=to_code,
        decision=decision,
        reason="because",
        decided_by="human",
        date="2026-11-22",
    )


def test_accept_route_upgrades_suspect_to_reviewed():
    quality, note = sr.apply_quality(sr.QUALITY_SUSPECT, review(sr.ACCEPT_ROUTE))
    assert quality == sr.QUALITY_REVIEWED
    assert "accepted the route" in note


def test_needs_bridge_keeps_suspect():
    quality, note = sr.apply_quality(sr.QUALITY_SUSPECT, review(sr.NEEDS_BRIDGE))
    assert quality == sr.QUALITY_SUSPECT
    assert "needs a bridge" in note


def test_review_without_decision_is_noop():
    quality, note = sr.apply_quality(sr.QUALITY_SUSPECT, None)
    assert quality == sr.QUALITY_SUSPECT
    assert note == ""


def test_review_on_clean_segment_is_ignored():
    quality, note = sr.apply_quality("osm_routed", review(sr.ACCEPT_ROUTE))
    assert quality == "osm_routed"
    assert "ignored" in note


def test_review_on_unmeasured_segment_is_ignored():
    quality, note = sr.apply_quality("unmeasured", review(sr.ACCEPT_ROUTE))
    assert quality == "unmeasured"
    assert "ignored" in note


def test_client_key_is_order_independent():
    forward = review(sr.ACCEPT_ROUTE, "KH", "MA")
    backward = review(sr.ACCEPT_ROUTE, "MA", "KH")
    assert forward.key == backward.key


def test_load_reads_the_committed_empty_file():
    """The committed file has no decisions; the loader must not invent any."""
    reviews = sr.load()
    assert reviews == []


def test_load_parses_a_real_entry(tmp_path):
    path = tmp_path / "segment_reviews.yaml"
    path.write_text(
        """
reviews:
  - from: "MSG"
    to: "BTT"
    decision: "accept_route"
    reason: "the line really does loop here"
    decided_by: "human"
    date: "2026-11-22"
""",
        encoding="utf-8",
    )
    reviews = sr.load(path)
    assert len(reviews) == 1
    assert reviews[0].key == ("BTT", "MSG")
    assert reviews[0].decision == sr.ACCEPT_ROUTE
    assert reviews[0].decided_by == "human"


def test_load_rejects_an_unknown_decision(tmp_path):
    path = tmp_path / "segment_reviews.yaml"
    path.write_text(
        """
reviews:
  - from: "A"
    to: "B"
    decision: "looks_fine_to_me"
    reason: "?"
    decided_by: "human"
    date: "2026-11-22"
""",
        encoding="utf-8",
    )
    assert sr.load(path) == []
