"""Phase 1 runner: index parsing, pilot table parsing, validators, review artifact.

Steps (AGENTS.md Phase 1, split per the human's plan):

- 1b: intercity index -> ``data/parsed/expected_trains_intercity.json``
- 1c: pilot pages 521-522 -> ``data/parsed/pilot_249_250.json``
- reconciliation index vs table headers -> ``data/review/``
- V1-V3 -> ``data/validated/``
- human review artifact -> ``data/review/pilot_249_250.html``

Nothing here writes to the raw layer.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pymupdf

from pipeline.parsers.index_table import parse_index_pages
from pipeline.parsers.stop_table import (
    footnote_patterns,
    merge_continuations,
    parse_page,
)
from pipeline.parsers.table_geometry import Word, split_tables, words_from_raw
from pipeline.validators import run_validators

DEFAULT_PDF = Path("data/input/GAPEKA_2026.pdf")
WORDS_DIR = Path("data/raw/words")
PARSED_DIR = Path("data/parsed")
REVIEW_DIR = Path("data/review")
VALIDATED_DIR = Path("data/validated")

PILOT_PAGES = (521, 522)
INDEX_PAGES = (53, 54, 55, 56, 57)

# Station codes as printed in tables: "Name (CODE)".
STATION_CODE_RE = re.compile(r"\(([A-Z]{2,5})\)")

# Printed-page offsets established in Phase 0 (report section 8).
INTERCITY_BOOK_OFFSETS = [(58, 664, 57), (670, 811, 669)]


def load_words(page: int, words_dir: Path = WORDS_DIR) -> list[Word]:
    payload = json.loads((words_dir / f"page_{page:04d}.json").read_text(encoding="utf-8"))
    return words_from_raw(payload)


def vertical_rulings(pdf: Path, page: int) -> list[float]:
    """Vertical ruling x-positions on a page (the document's own cell borders)."""
    doc = pymupdf.open(pdf)
    try:
        drawings = doc[page - 1].get_drawings()
    finally:
        doc.close()

    xs: set[float] = set()
    for path in drawings:
        for item in path["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.x - b.x) < 0.5:
                    xs.add(round(a.x, 1))
            elif item[0] == "re":
                rect = item[1]
                if rect.width < 1.5:
                    xs.add(round(rect.x0, 1))
    return sorted(xs)


def mapped_pdf_page(printed: str | None) -> int | None:
    """Map a printed intercity page number to a PDF page using the offset table."""
    if printed is None or not printed.isdigit():
        return None
    number = int(printed)
    for start, end, offset in INTERCITY_BOOK_OFFSETS:
        candidate = number + offset
        if start <= candidate <= end:
            return candidate
    return None


# --- cross-parser checks ----------------------------------------------------


def pdftotext_layout(pdf: Path, page: int) -> str | None:
    """Cross-check with ``pdftotext -layout``; returns None if unavailable."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def pdfplumber_words(pdf: Path, page: int) -> list[str] | None:
    """Cross-check with pdfplumber; returns None if unavailable."""
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError:
        return None
    try:
        with pdfplumber.open(pdf) as doc:
            return doc.pages[page - 1].extract_words()
    except Exception:  # noqa: BLE001 - a cross-checker must never break the run
        return None


def cross_parser_report(pdf: Path, pages: tuple[int, ...], trains: list[dict]) -> dict:
    """Compare our station sequence against pdfplumber and pdftotext.

    Differences are recorded, never hidden or "fixed".
    """
    report: dict = {
        "pages": {},
        "pdftotext": {"available": None},
        "pdfplumber": {"available": None},
        "differences": [],
    }

    for page in pages:
        ours = [
            s["station_code"]
            for t in trains
            for s in t["stops"]
            if s["provenance"]["page"] == page and s["station_code"]
        ]
        report["pages"][str(page)] = {"our_station_codes": ours}

        # --- pdfplumber ---
        plumber_words = pdfplumber_words(pdf, page)
        if plumber_words is None:
            report["pdfplumber"] = {"available": False, "reason": "pdfplumber not installed"}
        else:
            plumber_codes = STATION_CODE_RE.findall(" ".join(w["text"] for w in plumber_words))
            report["pdfplumber"] = {
                "available": True,
                "word_count": len(plumber_words),
                "page": page,
                "station_codes": plumber_codes,
                "missing_from_plumber": sorted(set(ours) - set(plumber_codes)),
                "missing_from_ours": sorted(set(plumber_codes) - set(ours)),
            }
            if set(ours) != set(plumber_codes):
                report["differences"].append(
                    {
                        "checker": "pdfplumber",
                        "page": page,
                        "only_in_ours": sorted(set(ours) - set(plumber_codes)),
                        "only_in_pdfplumber": sorted(set(plumber_codes) - set(ours)),
                    }
                )

        # --- pdftotext -layout ---
        text = pdftotext_layout(pdf, page)
        if text is None:
            report["pdftotext"] = {"available": False, "reason": "pdftotext not installed"}
        else:
            layout_codes = STATION_CODE_RE.findall(text)
            report["pdftotext"] = {
                "available": True,
                "page": page,
                "line_count": len([line for line in text.splitlines() if line.strip()]),
                "station_codes": layout_codes,
            }
            if set(ours) != set(layout_codes):
                report["differences"].append(
                    {
                        "checker": "pdftotext",
                        "page": page,
                        "only_in_ours": sorted(set(ours) - set(layout_codes)),
                        "only_in_pdftotext": sorted(set(layout_codes) - set(ours)),
                    }
                )

    report["note"] = (
        "Station-code sets are compared, not times: pdftotext and pdfplumber do not "
        "assign table cells, so a code-set mismatch is the strongest check they can "
        "make. Time-level agreement is checked against the index in "
        "reconciliation_intercity.json."
    )
    return report


# --- reconciliation ---------------------------------------------------------


def reconcile(index_entries: list[dict], trains: list[dict]) -> dict:
    """Compare index entries against table headers. Never auto-resolve."""
    index_by_no: dict[str, dict] = {}
    duplicates: list[str] = []
    for entry in index_entries:
        number = entry["train_no"]
        if number is None:
            continue
        if number in index_by_no:
            duplicates.append(number)
        index_by_no.setdefault(number, entry)

    table_by_no: dict[str, dict] = {}
    for train in trains:
        number = train["train_no"]
        if number is None:
            continue
        table_by_no[number] = train

    only_index = sorted(set(index_by_no) - set(table_by_no), key=_number_key)
    only_table = sorted(set(table_by_no) - set(index_by_no), key=_number_key)

    page_mismatches = []
    for number in sorted(set(index_by_no) & set(table_by_no), key=_number_key):
        expected = index_by_no[number]
        actual = table_by_no[number]
        if (
            expected.get("mapped_pdf_page") is not None
            and actual["page"] != expected["mapped_pdf_page"]
        ):
            page_mismatches.append(
                {
                    "train_no": number,
                    "index_printed_page": expected["printed_page"],
                    "index_mapped_pdf_page": expected["mapped_pdf_page"],
                    "parsed_table_pdf_page": actual["page"],
                }
            )

    return {
        "note": (
            "Index is the primary authority for which trains exist. Differences are "
            "listed, never resolved automatically."
        ),
        "index_entries": len(index_entries),
        "index_distinct_train_numbers": len(index_by_no),
        "duplicate_train_numbers_in_index": sorted(set(duplicates), key=_number_key),
        "pilot_table_trains": len(trains),
        "in_index_but_not_parsed": only_index,
        "parsed_but_not_in_index": only_table,
        "page_mismatches": page_mismatches,
    }


def _number_key(value: str) -> tuple[int, str]:
    digits = "".join(ch for ch in value if ch.isdigit())
    return (int(digits) if digits else 0, value)


# --- review artifact --------------------------------------------------------


def render_review_html(
    pdf: Path, trains: list[dict], reports: list[dict], footnotes: list[dict]
) -> str:
    rows: list[str] = []
    for train in trains:
        rows.append(
            f"<h2>KA {train['train_no'] or '?'} — {train['name'] or 'unknown'}"
            f" <small>({train['origin']}–{train['destination']})</small></h2>"
        )
        if train["needs_review"]:
            rows.append('<p class="flag">train-level: ' + "; ".join(train["needs_review"]) + "</p>")
        rows.append(
            "<table><tr><th>#</th><th>Station</th><th>Speed</th><th>Datang</th>"
            "<th>Berangkat</th><th>Keterangan</th><th>type</th></tr>"
        )
        for stop in train["stops"]:
            css = ' class="flag"' if stop["needs_review"] else ""
            cells = "".join(
                f"<td>{_cell_html(stop, key)}</td>" for key in ("speed", "arrive", "depart", "note")
            )
            rows.append(
                f"<tr{css}><td>{stop['seq']}</td>"
                f"<td>{stop['station_name']} ({stop['station_code'] or '?'})</td>"
                f"{cells}<td>{stop['stop_type']}</td></tr>"
            )
        rows.append("</table>")

    rule_rows = []
    for report in reports:
        status = "PASS" if report["passed"] else "FAIL"
        rule_rows.append(
            f'<tr class="{"ok" if report["passed"] else "flag"}">'
            f"<td>{report['rule']}</td><td>{report['description']}</td>"
            f"<td>{report['checked']}</td><td>{report['violation_count']}</td>"
            f"<td>{status}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pilot review — KA 249/250 (PDF 521-522)</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem; max-width: 1200px; }}
  table {{ border-collapse: collapse; margin: 1rem 0 2rem; font-size: 13px; }}
  th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
  th {{ background: #f0f0f0; }}
  .flag {{ background: #ffe0e0; }}
  .ok {{ background: #e0ffe0; }}
  h2 {{ margin-top: 2rem; }}
  small {{ color: #666; font-weight: normal; }}
  .page {{ border: 1px solid #999; margin: 1rem 0; }}
</style>
</head>
<body>
<h1>Phase 1 pilot review — KA 249 / KA 250</h1>
<p><strong>Status: DRAFT, generated by the parser. Not verified by a human.</strong></p>
<p>Rendered pages are produced locally and are gitignored; they are not embedded here.</p>

<h2>Validator results</h2>
<table>
<tr><th>Rule</th><th>Description</th><th>Checked</th><th>Violations</th><th>Result</th></tr>
{"".join(rule_rows)}
</table>

<h2>Footnote patterns (captured verbatim, not interpreted)</h2>
<ul>{"".join(f"<li><code>{f['text']}</code> ×{f['count']}</li>" for f in footnotes)}</ul>

{"".join(rows)}

<h2>Side-by-side check</h2>
<p>Render pages 521 and 522 (see <code>make inventory</code> notes) and compare against
the tables above. Every cell here carries a bbox in the JSON output, so a future
review UI can highlight its source words.</p>
</body>
</html>
"""


def _cell_html(stop: dict, key: str) -> str:
    cell = stop[key]
    value = cell["value"]
    raw = cell["raw"]
    if cell["page"] is None:
        return "<em>—</em>"
    if value is None and raw:
        return f"<em>{raw}</em>"
    return value if value is not None else "<em>—</em>"


# --- main -------------------------------------------------------------------


def run(pdf: Path, words_dir: Path = WORDS_DIR) -> int:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATED_DIR.mkdir(parents=True, exist_ok=True)

    # 1b — index
    index_words = {page: load_words(page, words_dir) for page in INDEX_PAGES}
    index_entries = [entry.as_dict() for entry in parse_index_pages(index_words)]
    for entry in index_entries:
        entry["mapped_pdf_page"] = mapped_pdf_page(entry["printed_page"])
    (PARSED_DIR / "expected_trains_intercity.json").write_text(
        json.dumps(
            {
                "note": "Index is the primary authority for which trains exist.",
                "pages": list(INDEX_PAGES),
                "mapped_by_offset_table": {
                    "intercity_book_1": "+57 for PDF 58-664",
                    "intercity_book_2": "+669 for PDF 670-811",
                },
                "entries": index_entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # 1c — pilot tables
    trains = []
    for page in PILOT_PAGES:
        words = load_words(page, words_dir)
        trains.extend(parse_page(split_tables(words, page, vertical_rulings(pdf, page))))
    trains = merge_continuations(trains)
    train_dicts = [t.as_dict() for t in trains]
    footnotes = footnote_patterns(trains)

    known_codes = {s.station_code for t in trains for s in t.stops if s.station_code}
    reports = run_validators(trains, known_codes)
    report_dicts = [r.as_dict() for r in reports]

    (PARSED_DIR / "pilot_249_250.json").write_text(
        json.dumps(
            {
                "verified_by_human": False,
                "note": (
                    "DRAFT generated by the parser. Regression fixture only until a "
                    "human confirms these rows against the PDF."
                ),
                "pages": list(PILOT_PAGES),
                "footnote_patterns": footnotes,
                "trains": train_dicts,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    reconciliation = reconcile(index_entries, train_dicts)
    (REVIEW_DIR / "reconciliation_intercity.json").write_text(
        json.dumps(reconciliation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    cross = cross_parser_report(pdf, PILOT_PAGES, train_dicts)
    (REVIEW_DIR / "cross_parser_pilot.json").write_text(
        json.dumps(cross, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    needs_review = []
    for train in train_dicts:
        for reason in train["needs_review"]:
            needs_review.append({"train_no": train["train_no"], "reason": reason})
        for stop in train["stops"]:
            for reason in stop["needs_review"]:
                needs_review.append(
                    {
                        "train_no": train["train_no"],
                        "page": stop["provenance"]["page"],
                        "seq": stop["seq"],
                        "station_code": stop["station_code"],
                        "reason": reason,
                    }
                )

    (VALIDATED_DIR / "pilot_249_250_validation.json").write_text(
        json.dumps(
            {
                "verified_by_human": False,
                "rules": report_dicts,
                "needs_review": needs_review,
                "all_rules_pass": all(r["passed"] for r in report_dicts),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    (REVIEW_DIR / "pilot_249_250.html").write_text(
        render_review_html(pdf, train_dicts, report_dicts, footnotes), encoding="utf-8"
    )

    # console summary
    print(f"index entries: {len(index_entries)}  (from pages {list(INDEX_PAGES)})")
    print(f"pilot trains: {len(train_dicts)}")
    for train in train_dicts:
        stops = len(train["stops"])
        print(f"  KA {train['train_no']}: {stops} stops  review={len(train['needs_review'])}")
    for report in report_dicts:
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"  {report['rule']} {status}: checked={report['checked']} "
            f"violations={report['violation_count']}"
        )
    print(f"needs_review items: {len(needs_review)}")
    print(
        f"cross-parser: pdftotext available={cross['pdftotext']['available']}, "
        f"pdfplumber available={cross['pdfplumber']['available']}"
    )
    print(f"wrote {PARSED_DIR}, {REVIEW_DIR}, {VALIDATED_DIR}")
    return 0 if all(r["passed"] for r in report_dicts) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1: index + pilot + validators.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--words", type=Path, default=WORDS_DIR)
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"error: PDF not found at {args.pdf}", file=sys.stderr)
        return 2
    if not (args.words / "manifest.json").exists():
        print(
            f"error: raw words missing at {args.words}; run `make extract` first",
            file=sys.stderr,
        )
        return 2
    return run(args.pdf, args.words)


if __name__ == "__main__":
    raise SystemExit(main())
