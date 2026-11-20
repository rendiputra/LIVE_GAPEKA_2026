"""Defensive guards: every parsed row reaches the review HTML (C3).

This is a structural guard with no known defect behind it. If the renderer ever
drops a row, a human reviewer would silently miss it, which is exactly the kind
of failure that erodes trust in a review pack.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REVIEW_DIR = Path("data/review")
PARSED_FILES = {
    "pilot_249_250": Path("data/parsed/pilot_249_250.json"),
    "pilot_259F_260F": Path("data/parsed/pilot_259F_260F.json"),
}
INTERCITY_PARSED = Path("data/parsed/intercity_trips.json")


class StopRowCounter(HTMLParser):
    """Count ``<tr>`` rows inside ``table.stops`` tables, and record train headings."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict] = []
        self.stops_tables: list[int] = []
        self._depth = 0
        self._current_table_is_stops = False

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "table":
            self._depth += 1
            classes = (attr.get("class") or "").split()
            self._current_table_is_stops = "stops" in classes
            if self._current_table_is_stops:
                self.stack.append({"rows": 0})
        elif tag == "tr" and self._current_table_is_stops and self.stack:
            self.stack[-1]["rows"] += 1

    def handle_endtag(self, tag):
        if tag == "table":
            if self._current_table_is_stops and self.stack:
                # Subtract the header row; only data rows are compared.
                self.stops_tables.append(max(0, self.stack.pop()["rows"] - 1))
            self._current_table_is_stops = False
            self._depth -= 1


def count_stop_rows(markup: str) -> list[int]:
    parser = StopRowCounter()
    parser.feed(markup)
    return parser.stops_tables


def test_pilot_html_row_counts_match_json():
    """Each pilot HTML shows the same number of rows as its JSON holds."""
    for name, path in PARSED_FILES.items():
        html_path = REVIEW_DIR / f"{name}.html"
        if not html_path.exists() or not path.exists():
            pytest.skip("run `make parse` first")

        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = [len(train["stops"]) for train in payload["trains"]]
        actual = count_stop_rows(html_path.read_text(encoding="utf-8"))
        assert sorted(actual) == sorted(expected), (
            f"{name}: HTML rows {actual} != JSON rows {expected}"
        )


def test_no_train_is_silently_dropped_from_the_html():
    """Every train in the JSON must have a heading in the HTML."""
    for name, path in PARSED_FILES.items():
        html_path = REVIEW_DIR / f"{name}.html"
        if not html_path.exists() or not path.exists():
            pytest.skip("run `make parse` first")

        payload = json.loads(path.read_text(encoding="utf-8"))
        markup = html_path.read_text(encoding="utf-8")
        for train in payload["trains"]:
            if train["train_no"] is None:
                continue
            pattern = re.compile(rf"KA\s+{re.escape(train['train_no'])}\s+—")
            assert pattern.search(markup), f"{name}: KA {train['train_no']} missing from HTML"


def test_quarantined_train_shows_banner():
    """C4: IF any train is quarantined, the banner must appear.

    After the ADR 003 marker model nothing is quarantined, so the guard asserts
    the renderer's banner behaviour directly and only checks the artefact when a
    quarantine file is non-empty.
    """
    quarantine = Path("data/review/quarantine")
    has_quarantined = any(
        json.loads(p.read_text(encoding="utf-8")).get("count", 0) > 0
        for p in quarantine.glob("*.json")
    ) if quarantine.exists() else False

    if has_quarantined:
        needs_review = REVIEW_DIR / "intercity_needs_review.html"
        if not needs_review.exists():
            pytest.skip("run `make parse-intercity` first")
        assert "QUARANTINED" in needs_review.read_text(encoding="utf-8")
        return

    # Renderer-level assertion, independent of current data.
    from pipeline.review_html import render_review_html

    train = {
        "train_no": "X", "name": "N", "origin": "A", "destination": "B",
        "completeness": "complete", "column_source": "ruling",
        "info": [], "needs_review": [], "quarantined": True,
        "quarantine_reasons": ["test_reason"], "stops": [],
    }
    markup = render_review_html("t", [train], [], [])
    assert "QUARANTINED" in markup and "test_reason" in markup


def test_intercity_html_row_counts_match_payload():
    """If the Phase 2a sample is regenerated, its rows must match its trains."""
    sample = REVIEW_DIR / "intercity_sample.html"
    if not sample.exists() or not INTERCITY_PARSED.exists():
        pytest.skip("run `make parse-intercity` first")

    trains = json.loads(INTERCITY_PARSED.read_text(encoding="utf-8"))["trains"]
    by_no = {t["train_no"]: len(t["stops"]) for t in trains}
    markup = sample.read_text(encoding="utf-8")

    # Each stop row's first cell is its sequence number; the table's row count
    # must equal the referenced train's stop count. We check the totals instead
    # of per-train identity because the sample is a subset.
    rows = count_stop_rows(markup)
    assert rows, "sample has no stop tables"
    assert all(count > 0 for count in rows), "a sampled train rendered zero rows"
    assert set(rows).issubset(set(by_no.values())), "a rendered row count matches no parsed train"
