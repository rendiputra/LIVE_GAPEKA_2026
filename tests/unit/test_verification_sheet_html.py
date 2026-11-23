"""Regression tests for the verification sheet's embedded JSON (T1 bug).

The "Unduh verification_result.json" button did nothing because the JSON was
embedded with `html.escape(quote=True)`, which turns `"` into `&quot;`. HTML
entities are NOT decoded inside `<script>`, so the script was a syntax error
("Unexpected token '&'") and no click handler was ever attached.

These tests pin the contract: the JSON inside `<script>` must be valid JSON with
no HTML entities, and it must not be able to close the script tag.
"""

from __future__ import annotations

import json

from pipeline import verification_sheet


def _build_sheet(selection: dict) -> str:
    return verification_sheet.build(selection)


def _selection_json(html: str) -> str:
    """Extract the literal text of the embedded JSON.

    Terminated by the `];` line that closes the array. Splitting on the first `;`
    would be wrong: `&quot;` itself contains a semicolon, which is exactly the bug
    under test.
    """
    marker = "const SELECTION = "
    start = html.index(marker) + len(marker)
    end = html.index("\n];", start)
    # `\n];` is `\n` + `]` + `;`: the `]` closes the JSON array, so include it.
    return html[start : end + 2].strip()


def _minimal_selection() -> dict:
    return {
        "seed": 1,
        "requirements": {"book1": 1},
        "strata": {"book1": 1},
        "longest_trip_id": "b1-1-v1-01",
        "shortest_trip_id": "b1-1-v1-01",
        "trains": [
            {
                "trip_id": "b1-1-v1-01",
                "train_no": "1",
                "book": 1,
                "service_class": "reguler",
                "name": "Anggrek",
                "relation": "SBI-GMR",
                "status": "complete",
                "pages": [],
                "stops": 0,
                "reason": "test",
            }
        ],
    }


def test_embedded_selection_is_valid_json():
    """The root cause: entities made the JSON unparseable."""
    html = _build_sheet(_minimal_selection())
    literal = _selection_json(html)
    parsed = json.loads(literal)  # must not raise
    assert parsed[0]["train_no"] == "1"


def test_embedded_selection_contains_no_html_entities():
    html = _build_sheet(_minimal_selection())
    literal = _selection_json(html)
    for entity in ("&quot;", "&amp;", "&lt;", "&gt;", "&#x27;", "&#39;"):
        assert entity not in literal, f"{entity} inside <script> breaks JS parsing"


def test_embedded_json_cannot_close_the_script_tag():
    """A name containing `</script>` must not terminate the block."""
    selection = _minimal_selection()
    selection["trains"][0]["name"] = "Bad</script><script>alert(1)</script>"
    html = _build_sheet(selection)
    literal = _selection_json(html)
    assert "</script>" not in literal
    parsed = json.loads(literal)
    assert parsed[0]["name"].startswith("Bad")


def test_sheet_still_declares_the_download_button():
    html = _build_sheet(_minimal_selection())
    assert 'id="download"' in html
    assert "verification_result.json" in html
