"""Tests for the review HTML generator.

The critical invariant (H1): every table row must have exactly as many cells as
its header row. A malformed table silently misaligns a human's comparison, which
is worse than a failed test.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline.review_html import (
    STOP_TABLE_HEADERS,
    cell_html,
    esc,
    render_review_html,
    rule_table_html,
    stop_table_html,
)

REVIEW_DIR = Path("data/review")


class TableShape(HTMLParser):
    """Collect the cell count of every row, grouped by table."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[int]] = []
        self._current: list[int] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._current = []
            self.tables.append(self._current)
        elif tag == "tr" and self._current is not None:
            self._current.append(0)
        elif tag in ("td", "th") and self._current is not None and self._current:
            self._current[-1] += 1

    def handle_endtag(self, tag):
        if tag == "table":
            self._current = None


def table_shapes(markup: str) -> list[list[int]]:
    parser = TableShape()
    parser.feed(markup)
    return parser.tables


def test_esc_escapes_html():
    assert esc("<script>") == "&lt;script&gt;"
    assert esc(None) == ""


def test_cell_html_is_a_td():
    stop = {"speed": {"value": "100", "raw": "100"}}
    assert cell_html(stop, "speed").startswith("<td>")
    assert cell_html(stop, "speed").endswith("</td>")


def test_cell_html_shows_raw_for_unparsed():
    stop = {"arrive": {"value": None, "raw": "-"}}
    out = cell_html(stop, "arrive")
    assert "<td>" in out and "</td>" in out
    assert "<em>-</em>" in out


def test_cell_html_shows_both_when_raw_differs():
    stop = {"speed": {"value": "80", "raw": "80 "}}
    out = cell_html(stop, "speed")
    assert "80" in out


def _train(stops):
    return {
        "train_no": "1",
        "name": "Test",
        "origin": "A",
        "destination": "B",
        "completeness": "complete",
        "column_source": "ruling",
        "info": [],
        "needs_review": [],
        "stops": stops,
    }


def _stop(seq, arrive, depart, flags=None):
    return {
        "seq": seq,
        "station_name": "S",
        "station_code": "SS",
        "speed": {"value": "100", "raw": "100"},
        "arrive": {"value": arrive, "raw": arrive or "-"},
        "depart": {"value": depart, "raw": depart or "-"},
        "note": {"value": None, "raw": ""},
        "stop_type": "stop",
        "day_offset": 0,
        "info": [],
        "needs_review": flags or [],
        "provenance": {"page": 1},
    }


def test_stop_table_has_one_cell_per_header():
    html_markup = "\n".join(stop_table_html(_train([_stop(1, None, "08:00:00")])))
    shapes = table_shapes(html_markup)
    assert shapes == [[len(STOP_TABLE_HEADERS), len(STOP_TABLE_HEADERS)]]


def test_stop_table_row_width_matches_header_with_flags():
    stop = _stop(2, "09:00:00", "09:01:00", flags=["speed_blank"])
    html_markup = "\n".join(stop_table_html(_train([stop])))
    shapes = table_shapes(html_markup)
    assert all(width == len(STOP_TABLE_HEADERS) for width in shapes[0])


def test_rule_table_is_rectangular():
    reports = [
        {
            "rule": "V1",
            "label": "V1",
            "description": "monotonic",
            "checked": 10,
            "violation_count": 0,
            "passed": True,
        }
    ]
    shapes = table_shapes("\n".join(rule_table_html(reports)))
    assert shapes == [[5, 5]]


def test_full_document_tables_are_rectangular():
    trains = [
        _train([_stop(i, f"{8 + i:02d}:00:00", f"{8 + i:02d}:01:00") for i in range(1, 6)])
    ] * 3
    markup = render_review_html(
        "t",
        trains,
        [
            {
                "rule": "V1",
                "label": "V1",
                "description": "d",
                "checked": 1,
                "violation_count": 0,
                "passed": True,
            }
        ],
        [{"text": "= ka 46 (ka 46 //)", "count": 2}],
    )
    for table in table_shapes(markup):
        assert len(set(table)) == 1, f"ragged table: {table}"


@pytest.mark.parametrize("name", ["pilot_249_250", "pilot_259F_260F"])
def test_generated_review_html_is_well_formed(name):
    path = REVIEW_DIR / f"{name}.html"
    if not path.exists():
        pytest.skip(f"{path} not generated; run `make parse`")
    for index, table in enumerate(table_shapes(path.read_text(encoding="utf-8"))):
        assert len(set(table)) == 1, f"{name} table #{index} is ragged: {table}"


@pytest.mark.parametrize("name", ["pilot_249_250", "pilot_259F_260F"])
def test_generated_review_html_links_page_images(name):
    path = REVIEW_DIR / f"{name}.html"
    if not path.exists():
        pytest.skip("run `make parse`")
    markup = path.read_text(encoding="utf-8")
    assert 'class="stops"' in markup
    assert "page_05" in markup  # an image reference


def test_review_image_dir_is_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "data/review/img/" in gitignore
