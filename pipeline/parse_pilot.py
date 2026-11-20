"""Phase 1 runner: index parsing, pilot table parsing, validators, review artefacts.

Steps:

- 1b: intercity index -> ``data/parsed/expected_trains_intercity.json``
- 1c: pilot pages -> ``data/parsed/pilot_*.json``
- reconciliation index vs table headers -> ``data/review/``
- V1, V2, V3-circular, V3b -> ``data/validated/``
- cross-parser checks (pdfplumber table strategy, pdftotext -layout) -> ``data/review/``
- human review artefacts -> ``data/review/pilot_*.html``

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
    COMPLETENESS_TRUNCATED,
    finalize,
    footnote_patterns,
    merge_continuations,
    parse_page,
)
from pipeline.parsers.table_geometry import Word, split_tables, words_from_raw
from pipeline.review_html import render_page_image, render_review_html
from pipeline.station_codes import scan_words_dir, v3b_report
from pipeline.validators import run_validators

DEFAULT_PDF = Path("data/input/GAPEKA_2026.pdf")
WORDS_DIR = Path("data/raw/words")
PARSED_DIR = Path("data/parsed")
REVIEW_DIR = Path("data/review")
VALIDATED_DIR = Path("data/validated")

PILOT_249_250 = (521, 522)
PILOT_259_260 = (528,)
INDEX_PAGES = (53, 54, 55, 56, 57)

STATION_CODE_RE = re.compile(r"\(([A-Z]{2,5})\)")
TIME_CELL_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

# Printed-page offsets established in Phase 0 (report section 8).
INTERCITY_BOOK_OFFSETS = [(58, 664, 57), (670, 811, 669)]


def load_words(page: int, words_dir: Path = WORDS_DIR) -> list[Word]:
    payload = json.loads((words_dir / f"page_{page:04d}.json").read_text(encoding="utf-8"))
    return words_from_raw(payload)


def vertical_rulings(pdf: Path, page: int) -> list[float]:
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
    if printed is None or not printed.isdigit():
        return None
    number = int(printed)
    for start, end, offset in INTERCITY_BOOK_OFFSETS:
        candidate = number + offset
        if start <= candidate <= end:
            return candidate
    return None


# --- cross-checkers ---------------------------------------------------------


def tool_status() -> dict:
    """Report which optional cross-check tools are present."""
    pdftotext = None
    try:
        proc = subprocess.run(
            ["pdftotext", "-v"], capture_output=True, text=True, timeout=20, check=False
        )
        pdftotext = proc.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        pdftotext = False

    try:
        import pdfplumber  # noqa: F401, PLC0415

        plumber = True
    except ImportError:
        plumber = False

    return {"pdftotext": pdftotext, "pdfplumber": plumber}


def pdftotext_layout(pdf: Path, page: int) -> str | None:
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


def pdfplumber_table_cells(pdf: Path, page: int) -> list[dict] | None:
    """Extract table cells with pdfplumber's explicit ruling-line strategy.

    Returns ``None`` when pdfplumber is unavailable, so the caller can report
    SKIPPED rather than a silent pass.
    """
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError:
        return None

    cells: list[dict] = []
    try:
        with pdfplumber.open(pdf) as doc:
            tables = doc.pages[page - 1].find_tables(
                {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                }
            )
            for table_index, table in enumerate(tables):
                for row in table.extract():
                    for cell in row:
                        if cell and TIME_CELL_RE.match(cell.strip()):
                            cells.append({"table": table_index, "text": cell.strip(), "page": page})
    except Exception as error:  # noqa: BLE001 - a cross-checker must never break a run
        return [{"error": str(error)}]

    return cells


def cross_parser_report(
    pdf: Path,
    pages: tuple[int, ...],
    trains: list[dict],
    known_codes: set[str],
) -> dict:
    """Compare our output against pdfplumber and pdftotext. Differences are kept."""
    status = tool_status()
    report: dict = {
        "tools": status,
        "pages": {},
        "differences": [],
        "note": (
            "Both pdfplumber's table strategy and our parser use the page's ruling "
            "lines. Shared systematic errors are therefore still possible; these "
            "checks catch drift between implementations, not a wrong reading of a "
            "rule line."
        ),
    }

    for page in pages:
        our_stops = [s for t in trains for s in t["stops"] if s["provenance"]["page"] == page]
        ours = [s["station_code"] for s in our_stops if s["station_code"]]
        ours_times = sorted(
            cell["value"] for s in our_stops for cell in (s["arrive"], s["depart"]) if cell["value"]
        )
        report["pages"][str(page)] = {
            "our_station_codes": ours,
            "our_time_cells": ours_times,
        }

        # --- pdfplumber tables ---
        plumber_cells = pdfplumber_table_cells(pdf, page)
        if plumber_cells is None:
            report.setdefault("pdfplumber", {})[str(page)] = {"status": "SKIPPED"}
        elif plumber_cells and "error" in plumber_cells[0]:
            report.setdefault("pdfplumber", {})[str(page)] = {
                "status": "ERROR",
                "error": plumber_cells[0]["error"],
            }
        else:
            plumber_times = sorted(cell["text"] for cell in plumber_cells)
            only_ours = sorted(set(ours_times) - set(plumber_times))
            only_plumber = sorted(set(plumber_times) - set(ours_times))
            report.setdefault("pdfplumber", {})[str(page)] = {
                "status": "RAN",
                "time_cells": len(plumber_times),
                "our_time_cells": len(ours_times),
                "only_in_ours": only_ours,
                "only_in_pdfplumber": only_plumber,
                "match": not only_ours and not only_plumber,
            }
            if only_ours or only_plumber:
                report["differences"].append(
                    {
                        "checker": "pdfplumber",
                        "page": page,
                        "only_in_ours": only_ours,
                        "only_in_pdfplumber": only_plumber,
                    }
                )

        # --- pdftotext -layout ---
        text = pdftotext_layout(pdf, page)
        if text is None:
            report.setdefault("pdftotext", {})[str(page)] = {"status": "SKIPPED"}
        else:
            layout_codes = STATION_CODE_RE.findall(text)
            only_ours = sorted(set(ours) - set(layout_codes))
            only_layout = sorted(set(layout_codes) - set(ours))
            report.setdefault("pdftotext", {})[str(page)] = {
                "status": "RAN",
                "station_codes": sorted(set(layout_codes)),
                "only_in_ours": only_ours,
                "only_in_pdftotext": only_layout,
                "match": not only_ours and not only_layout,
            }
            if only_ours or only_layout:
                report["differences"].append(
                    {
                        "checker": "pdftotext",
                        "page": page,
                        "only_in_ours": only_ours,
                        "only_in_pdftotext": only_layout,
                    }
                )

    return report


# --- R4a: index vs parsed endpoint times ------------------------------------


def index_time_cross_check(index_entries: list[dict], trains: list[dict]) -> dict:
    """Compare index departure/arrival with parsed first departure / last arrival."""
    by_no: dict[str, dict] = {}
    for entry in index_entries:
        numbers = (entry["train_no"] or "").split("-")
        for number in numbers:
            if number:
                by_no.setdefault(number, entry)

    results = []
    for train in trains:
        number = train["train_no"]
        entry = by_no.get(number or "")
        if entry is None:
            results.append({"train_no": number, "status": "not_in_index", "mismatches": []})
            continue

        first_depart = next(
            (s["depart"]["value"] for s in train["stops"] if s["depart"]["value"]), None
        )
        last_arrive = None
        for stop in reversed(train["stops"]):
            if stop["arrive"]["value"]:
                last_arrive = stop["arrive"]["value"]
                break

        mismatches = []
        truncated = train.get("completeness") == COMPLETENESS_TRUNCATED
        for label, index_value, ours in (
            ("departure", entry.get("depart"), first_depart),
            ("arrival", entry.get("arrive"), last_arrive),
        ):
            if index_value is None or ours is None:
                mismatches.append(
                    {"field": label, "index": index_value, "parsed": ours, "reason": "missing"}
                )
                continue
            if label == "arrival" and truncated:
                # A truncated trip cannot reach its destination, so comparing the
                # last parsed arrival with the index's terminal arrival is not a
                # mismatch; it is the expected consequence of the page range.
                mismatches.append(
                    {
                        "field": label,
                        "index": index_value,
                        "parsed": ours,
                        "reason": "truncated_trip_not_comparable",
                    }
                )
                continue
            if index_value[:5] != ours[:5]:
                mismatches.append(
                    {"field": label, "index": index_value, "parsed": ours, "reason": "value"}
                )

        results.append(
            {
                "train_no": number,
                "completeness": train.get("completeness"),
                "index_depart": entry.get("depart"),
                "parsed_first_depart": first_depart,
                "index_arrive": entry.get("arrive"),
                "parsed_last_arrive": last_arrive,
                "mismatches": mismatches,
            }
        )
    real_mismatches = sum(
        1
        for r in results
        for m in r["mismatches"]
        if m["reason"] not in ("truncated_trip_not_comparable",)
    )
    return {
        "rule": "R4a",
        "description": "index departure/arrival vs parsed endpoints (minute precision)",
        "results": results,
        "mismatch_count": real_mismatches,
        "non_comparable_count": sum(
            1
            for r in results
            for m in r["mismatches"]
            if m["reason"] == "truncated_trip_not_comparable"
        ),
    }


# --- R5: seconds ------------------------------------------------------------


def seconds_report(trains: list[dict]) -> dict:
    total = non_zero = 0
    examples = []
    for train in trains:
        for stop in train["stops"]:
            for cell in (stop["arrive"], stop["depart"]):
                value = cell["value"]
                if not value:
                    continue
                total += 1
                seconds = int(value.split(":")[2])
                if seconds != 0:
                    non_zero += 1
                    if len(examples) < 20:
                        examples.append(
                            {
                                "train_no": train["train_no"],
                                "seq": stop["seq"],
                                "station": stop["station_code"],
                                "value": value,
                            }
                        )
    return {
        "time_values": total,
        "with_non_zero_seconds": non_zero,
        "non_zero_examples": examples,
        "all_seconds_zero": non_zero == 0,
    }


def seconds_report_all_sections_words(words_dir: Path = WORDS_DIR) -> dict:
    """Count non-zero seconds per page section, straight from the raw words."""
    inventory_path = Path("data/raw/inventory.json")
    sections: dict[str, dict[str, int]] = {}
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    by_page = {p["page"]: p["section"] for p in inventory["pages"]}

    pattern = re.compile(r"\b\d{2}:\d{2}:(\d{2})\b")
    for path in sorted(words_dir.glob("page_*.json")):
        page = int(path.stem.split("_")[1])
        section = by_page.get(page, "unknown")
        text = " ".join(row[4] for row in json.loads(path.read_text(encoding="utf-8"))["words"])
        bucket = sections.setdefault(section, {"total": 0, "non_zero": 0})
        for seconds in pattern.findall(text):
            bucket["total"] += 1
            if seconds != "00":
                bucket["non_zero"] += 1
    return sections


# --- R6: index rows vs train numbers ---------------------------------------


def index_flatten(index_entries: list[dict]) -> dict:
    """Flatten multi-number index rows into per-train-number records."""
    flattened = []
    for entry in index_entries:
        numbers = [n for n in (entry["train_no"] or "").split("-") if n]
        for number in numbers:
            flattened.append(
                {
                    "train_no": number,
                    "seq": entry["seq"],
                    "row_train_no": entry["train_no"],
                    "name": entry["name"],
                    "relation": entry["relation"],
                    "printed_page": entry["printed_page"],
                }
            )
    counts: dict[str, int] = {}
    for item in flattened:
        counts[item["train_no"]] = counts.get(item["train_no"], 0) + 1
    return {
        "rows": len(index_entries),
        "flattened_records": len(flattened),
        "distinct_train_numbers": len(counts),
        "multi_number_rows": sum(
            1 for e in index_entries if e["train_no"] and "-" in e["train_no"]
        ),
        "duplicated_train_numbers": {
            number: count for number, count in sorted(counts.items()) if count > 1
        },
        "flattened": flattened,
    }


def book_reconciliation(index_entries: list[dict], trains: list[dict]) -> dict:
    """Per-book lists: in tables but not index, and the reverse. Never resolved."""
    index_numbers: set[str] = set()
    for entry in index_entries:
        index_numbers.update(n for n in (entry["train_no"] or "").split("-") if n)

    table_numbers: set[str] = set()
    for train in trains:
        if train["train_no"]:
            table_numbers.update(n for n in train["train_no"].split("-") if n)

    return {
        "note": "Listed, never resolved.",
        "index_distinct_numbers": len(index_numbers),
        "pilot_table_numbers": sorted(table_numbers),
        "in_tables_but_absent_from_index": sorted(table_numbers - index_numbers),
        "in_index_but_absent_from_tables": sorted(index_numbers - table_numbers),
        "index_side_is_large_by_design": (
            "The index covers the whole intercity section; the pilot parses two pages."
        ),
    }


# --- review artefacts -------------------------------------------------------


# --- pipeline pieces --------------------------------------------------------


def parse_pages(pdf: Path, pages: tuple[int, ...], words_dir: Path) -> list:
    trains = []
    for page in pages:
        words = load_words(page, words_dir)
        trains.extend(parse_page(split_tables(words, page, vertical_rulings(pdf, page))))
    trains = merge_continuations(trains)
    return finalize(trains, (min(pages), max(pages)))


def info_and_review_counts(trains: list[dict]) -> dict:
    info = sum(len(t["info"]) for t in trains) + sum(
        len(s["info"]) for t in trains for s in t["stops"]
    )
    review = sum(len(t["needs_review"]) for t in trains) + sum(
        len(s["needs_review"]) for t in trains for s in t["stops"]
    )
    return {"info": info, "needs_review": review}


def run(pdf: Path, words_dir: Path = WORDS_DIR) -> int:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATED_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1b: index ---
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

    # --- V3b over all raw pages ---
    code_index = scan_words_dir(words_dir)
    v3b = v3b_report(code_index)
    known_codes = set(code_index.code_to_names)

    # --- 1c: two pilots ---
    pilots = {
        "pilot_249_250": parse_pages(pdf, PILOT_249_250, words_dir),
        "pilot_259F_260F": parse_pages(pdf, PILOT_259_260, words_dir),
    }

    summary: dict = {}
    for name, trains in pilots.items():
        train_dicts = [t.as_dict() for t in trains]
        footnotes = footnote_patterns(trains)
        reports = run_validators(trains, known_codes)

        # V3 is circular; label it and keep it informational.
        report_dicts = []
        for report in reports:
            payload = report.as_dict()
            if report.rule == "V3":
                payload["rule"] = "V3"
                payload["label"] = "V3-circular: informational"
                payload["circular"] = True
                payload["note"] = (
                    "Stations table is built from the same parsed rows, so this "
                    "cannot detect a wrong station code. V3b is the non-circular "
                    "check."
                )
            else:
                payload["label"] = report.rule
                payload["circular"] = False
            report_dicts.append(payload)

        (PARSED_DIR / f"{name}.json").write_text(
            json.dumps(
                {
                    "verified_by_human": False,
                    "note": (
                        "DRAFT generated by the parser. Regression fixture only until "
                        "a human confirms these rows against the PDF."
                    ),
                    "pages": list(name == "pilot_249_250" and PILOT_249_250 or PILOT_259_260),
                    "footnote_patterns": footnotes,
                    "trains": train_dicts,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        needs_review_items = []
        for train in train_dicts:
            for reason in train["needs_review"]:
                needs_review_items.append({"train_no": train["train_no"], "reason": reason})
            for stop in train["stops"]:
                for reason in stop["needs_review"]:
                    needs_review_items.append(
                        {
                            "train_no": train["train_no"],
                            "page": stop["provenance"]["page"],
                            "seq": stop["seq"],
                            "station_code": stop["station_code"],
                            "reason": reason,
                        }
                    )

        truncated = [
            t["train_no"] for t in train_dicts if t["completeness"] == COMPLETENESS_TRUNCATED
        ]

        (VALIDATED_DIR / f"{name}_validation.json").write_text(
            json.dumps(
                {
                    "verified_by_human": False,
                    "rules": report_dicts,
                    "v3b": {
                        "code_conflict_count": v3b["code_conflict_count"],
                        "name_conflict_count": v3b["name_conflict_count"],
                        "near_duplicate_count": v3b["near_duplicate_count"],
                        "prefix_pair_count": v3b["prefix_pair_count"],
                        "full": v3b,
                    },
                    "needs_review": needs_review_items,
                    "counts": info_and_review_counts(train_dicts),
                    "truncated_trains": truncated,
                    "all_rules_pass": all(r["passed"] for r in report_dicts),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        cross = cross_parser_report(
            pdf,
            tuple(sorted({p for p in (521, 522) if name == "pilot_249_250"}) or PILOT_259_260),
            train_dicts,
            known_codes,
        )
        (REVIEW_DIR / f"cross_parser_{name}.json").write_text(
            json.dumps(cross, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        # Render every source page next to its table so verification needs no
        # PDF reader. Images are gitignored.
        pages_used = sorted({s["provenance"]["page"] for t in train_dicts for s in t["stops"]})
        images: dict[int, str] = {}
        for page in pages_used:
            target = render_page_image(pdf, page, REVIEW_DIR)
            if target is not None:
                images[page] = f"{target.parent.name}/{target.name}"

        (REVIEW_DIR / f"{name}.html").write_text(
            render_review_html(
                f"Phase 1 review — {name}",
                train_dicts,
                report_dicts,
                footnotes,
                images=images,
                notes=(
                    "<p>A cell shows the parsed value; the printed token appears in "
                    "grey when it differs, or in italics when it was not converted. "
                    "Rows with <em>needs_review</em> flags are highlighted.</p>"
                ),
            ),
            encoding="utf-8",
        )

        summary[name] = {
            "trains": len(train_dicts),
            "stops": sum(len(t["stops"]) for t in train_dicts),
            "counts": info_and_review_counts(train_dicts),
            "truncated": truncated,
        }

    # --- R4a: index time cross-check on both pilots ---
    all_trains = [t for trains in pilots.values() for t in trains]
    r4a = index_time_cross_check(index_entries, [t.as_dict() for t in all_trains])
    (REVIEW_DIR / "r4a_index_time_check.json").write_text(
        json.dumps(r4a, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # --- R5: seconds ---
    r5 = {
        "pilot_trains": seconds_report([t.as_dict() for t in all_trains]),
        "per_section_raw": seconds_report_all_sections_words(words_dir),
    }
    (REVIEW_DIR / "r5_seconds.json").write_text(
        json.dumps(r5, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # --- R6: index units ---
    r6 = {
        "flatten": {k: v for k, v in index_flatten(index_entries).items() if k != "flattened"},
        "book_reconciliation": book_reconciliation(
            index_entries, [t.as_dict() for t in all_trains]
        ),
    }
    (REVIEW_DIR / "r6_index_units.json").write_text(
        json.dumps(r6, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (PARSED_DIR / "index_flattened_train_numbers.json").write_text(
        json.dumps(index_flatten(index_entries), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # --- console ---
    print(f"index entries: {len(index_entries)}")
    print(
        f"V3b: codes={v3b['distinct_codes']} names={v3b['distinct_names']} "
        f"code_conflicts={v3b['code_conflict_count']} "
        f"name_conflicts={v3b['name_conflict_count']}"
    )
    for name, payload in summary.items():
        print(
            f"{name}: trains={payload['trains']} stops={payload['stops']} "
            f"info={payload['counts']['info']} review={payload['counts']['needs_review']} "
            f"truncated={payload['truncated']}"
        )
    print(f"R4a mismatches: {r4a['mismatch_count']}")
    print(f"R5 non-zero seconds (pilot): {r5['pilot_trains']['with_non_zero_seconds']}")
    print(f"tools: {tool_status()}")
    print(f"wrote {PARSED_DIR}, {REVIEW_DIR}, {VALIDATED_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1: index + pilots + validators.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--words", type=Path, default=WORDS_DIR)
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"error: PDF not found at {args.pdf}", file=sys.stderr)
        return 2
    if not (args.words / "manifest.json").exists():
        print(
            f"error: raw words missing at {args.words}; run `make extract` first", file=sys.stderr
        )
        return 2
    return run(args.pdf, args.words)


if __name__ == "__main__":
    raise SystemExit(main())
