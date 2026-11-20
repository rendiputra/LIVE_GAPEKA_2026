"""Phase 2a: parse the whole of intercity Book 1 and gate it.

Scope: every ``train_table`` page whose subtype is ``intercity_train_table``
(Book 1, approx. PDF 52-669). Book 2 (local), KRL, and freight are out of scope.

Gate: a train enters ``data/validated/`` only when

- ``completeness == complete``, and
- V1, V2, and V8 pass, and
- it has zero unresolved ``needs_review`` items.

Everything else goes to ``data/review/quarantine/`` with machine-readable reasons.
No train is ever hand-fixed; a failure is listed.

Usage:
    python -m pipeline.parse_intercity [--limit N]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

from pipeline.parsers.stop_table import (
    COMPLETENESS_COMPLETE,
    finalize,
    footnote_patterns,
    merge_continuations,
    parse_page,
    seconds_of,
)
from pipeline.parsers.table_geometry import split_tables, words_from_raw
from pipeline.review_html import render_page_image, render_review_html
from pipeline.service_class import build_index
from pipeline.service_class import join as join_service_class
from pipeline.validators import validate_v1, validate_v2
from pipeline.validators_phase2 import validate_v10, validate_v11

DEFAULT_PDF = Path("data/input/GAPEKA_2026.pdf")
INVENTORY = Path("data/raw/inventory.json")
WORDS_DIR = Path("data/raw/words")
PARSED_DIR = Path("data/parsed")
REVIEW_DIR = Path("data/review")
QUARANTINE_DIR = REVIEW_DIR / "quarantine"
VALIDATED_DIR = Path("data/validated")
DOCS = Path("docs")

BOOK1_SUBTYPE = "intercity_train_table"
BOOK2_SUBTYPE = "local_train_table"
SAMPLE_SEED = 20261120
SAMPLE_SIZE = 25


# --- scope ------------------------------------------------------------------


def pages_for_subtype(subtype: str, inventory_path: Path = INVENTORY) -> list[int]:
    """Every train_table page with the given subtype."""
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    return [
        page["page"]
        for page in inventory["pages"]
        if page["type"] == "train_table" and page["subtype"] == subtype
    ]


def book1_pages(inventory_path: Path = INVENTORY) -> list[int]:
    """Book 1 (intercity) pages."""
    return pages_for_subtype(BOOK1_SUBTYPE, inventory_path)


def book2_pages(inventory_path: Path = INVENTORY) -> list[int]:
    """Book 2 (local) pages."""
    return pages_for_subtype(BOOK2_SUBTYPE, inventory_path)


def vertical_rulings(doc: pymupdf.Document, page: int) -> list[float]:
    drawings = doc[page - 1].get_drawings()
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


# --- parsing ----------------------------------------------------------------


def parse_book1(pdf: Path, pages: list[int], words_dir: Path = WORDS_DIR) -> tuple[list, list[int]]:
    """Parse every page in scope, in order, and merge continuations."""
    doc = pymupdf.open(pdf)
    try:
        trains = []
        parsed_pages: list[int] = []
        for page in pages:
            path = words_dir / f"page_{page:04d}.json"
            if not path.exists():
                continue
            words = words_from_raw(json.loads(path.read_text(encoding="utf-8")))
            blocks = split_tables(words, page, vertical_rulings(doc, page))
            trains.extend(parse_page(blocks))
            parsed_pages.append(page)
    finally:
        doc.close()

    trains = merge_continuations(trains)
    return finalize(trains, (min(pages), max(pages))), parsed_pages


# --- validators added in Phase 2a -------------------------------------------


def _relation_endpoints(train) -> tuple[str | None, str | None]:
    if train.origin and train.destination:
        return train.origin, train.destination
    return None, None


def validate_v8(trains: list) -> dict:
    """V8: first station = relation origin, last station = relation destination.

    Trains with multiple numbers or relations are reported, not guessed.
    """
    results = []
    passed = 0
    for train in trains:
        origin, destination = _relation_endpoints(train)
        first = train.stops[0].station_code if train.stops else None
        last = train.stops[-1].station_code if train.stops else None

        multi = train.train_no is not None and "-" in train.train_no
        if multi or origin is None or destination is None:
            results.append(
                {
                    "train_no": train.train_no,
                    "status": "reported_not_checked",
                    "reason": "multi-number row or missing relation",
                    "origin": origin,
                    "destination": destination,
                    "first_station": first,
                    "last_station": last,
                }
            )
            continue

        problems = []
        if first != origin:
            problems.append(f"first station {first} != origin {origin}")
        if train.completeness == COMPLETENESS_COMPLETE and last != destination:
            problems.append(f"last station {last} != destination {destination}")

        if problems:
            results.append(
                {
                    "train_no": train.train_no,
                    "status": "fail",
                    "problems": problems,
                    "origin": origin,
                    "destination": destination,
                    "first_station": first,
                    "last_station": last,
                }
            )
        else:
            passed += 1

    return {
        "rule": "V8",
        "description": "first station = relation origin; last station = relation destination",
        "checked": passed + sum(1 for r in results if r["status"] == "fail"),
        "passed": passed,
        "reported_not_checked": sum(1 for r in results if r["status"] == "reported_not_checked"),
        "violations": [r for r in results if r["status"] == "fail"],
        "reported": [r for r in results if r["status"] == "reported_not_checked"],
    }


def validate_v9(trains: list) -> dict:
    """V9: segment running times are consistent across trains. Report only."""
    segments: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for train in trains:
        timed = []
        for stop in train.stops:
            reference = stop.depart.value or stop.arrive.value
            seconds = seconds_of(reference)
            if seconds is not None:
                timed.append((seconds, stop))
        for (prev_s, prev_stop), (cur_s, cur_stop) in zip(timed, timed[1:], strict=False):
            delta = cur_s - prev_s
            if delta < 0:
                delta += 24 * 3600
            if prev_stop.station_code and cur_stop.station_code and delta > 0:
                segments[(prev_stop.station_code, cur_stop.station_code)].append(
                    {"train_no": train.train_no, "seconds": delta}
                )

    outliers = []
    single_train_pairs = []
    distributions = {}
    for pair, observations in sorted(segments.items()):
        values = sorted(o["seconds"] for o in observations)
        median = values[len(values) // 2]
        distributions[f"{pair[0]}->{pair[1]}"] = {
            "count": len(values),
            "min": values[0],
            "median": median,
            "max": values[-1],
        }
        if len(observations) == 1:
            single_train_pairs.append(
                {"pair": f"{pair[0]}->{pair[1]}", "train_no": observations[0]["train_no"]}
            )
            continue
        for observation in observations:
            if median and observation["seconds"] > median * 2:
                outliers.append(
                    {
                        "pair": f"{pair[0]}->{pair[1]}",
                        "train_no": observation["train_no"],
                        "seconds": observation["seconds"],
                        "median": median,
                    }
                )

    return {
        "rule": "V9",
        "description": "segment running-time consistency across trains (report only)",
        "segments": len(segments),
        "observations": sum(len(v) for v in segments.values()),
        "single_train_pairs": single_train_pairs,
        "single_train_pair_count": len(single_train_pairs),
        "outliers": outliers,
        "outlier_count": len(outliers),
        "distributions": distributions,
    }


def validate_v4(
    trains: list, index_entries: list[dict], offset_table: list[tuple[int, int, int]]
) -> dict:
    """V4: reconcile parsed trains against index rows and Relasi headers."""

    def split_numbers(text: str | None) -> list[str]:
        if not text:
            return []
        parts = text.split("-")
        if len(parts) > 1 and all(re.match(r"^\d{1,4}[A-Z]?$", p) for p in parts):
            return parts
        return [text]

    index_numbers: dict[str, dict] = {}
    for entry in index_entries:
        printed = entry.get("printed_page")
        mapped = None
        if printed and printed.isdigit():
            candidate = int(printed)
            for start, end, offset in offset_table:
                if start <= candidate + offset <= end:
                    mapped = candidate + offset
                    break
        for number in split_numbers(entry["train_no"]):
            index_numbers.setdefault(
                number,
                {
                    "seq": entry["seq"],
                    "name": entry["name"],
                    "relation": entry["relation"],
                    "printed_page": printed,
                    "mapped_pdf_page": mapped,
                },
            )

    table_numbers: dict[str, dict] = {}
    for train in trains:
        for number in split_numbers(train.train_no):
            table_numbers.setdefault(
                number,
                {
                    "page": train.page,
                    "name": train.name,
                    "relation": f"{train.origin}-{train.destination}",
                    "completeness": train.completeness,
                },
            )

    both = set(index_numbers) & set(table_numbers)
    page_mismatch = []
    multi_number_rows = {
        number
        for entry in index_entries
        for number in split_numbers(entry["train_no"])
        if entry["train_no"] and "-" in entry["train_no"]
    }
    for number in sorted(both, key=lambda n: (len(n), n)):
        expected = index_numbers[number]["mapped_pdf_page"]
        actual = table_numbers[number]["page"]
        if expected is None or actual == expected:
            continue
        if number in multi_number_rows:
            # The index gives one page for a multi-number row; each constituent
            # train may start on a different page. Not a mismatch.
            continue
        page_mismatch.append(
            {
                "train_no": number,
                "index_mapped_pdf_page": expected,
                "parsed_pdf_page": actual,
                "delta": actual - expected,
            }
        )

    no_page_column = not any(entry.get("printed_page") for entry in index_entries)
    return {
        "rule": "V4",
        "description": "parsed trains vs index and Relasi headers (list only, never resolved)",
        "index_has_page_column": not no_page_column,
        "index_numbers": len(index_numbers),
        "table_numbers": len(table_numbers),
        "in_both": len(both),
        "in_index_not_in_tables": sorted(set(index_numbers) - set(table_numbers)),
        "in_tables_not_in_index": sorted(set(table_numbers) - set(index_numbers)),
        "page_mismatches": page_mismatch,
        "page_mismatch_count": len(page_mismatch),
    }


# --- pass-row and footnote audits -------------------------------------------


def audit_pass_rows(trains: list) -> dict:
    """Count Ls rows and list every counter-example of the stated convention."""
    ls_total = 0
    ls_with_arrive = []
    ls_with_two_times = []
    ls_without_any_time = []
    single_time_non_ls = []

    for train in trains:
        for index, stop in enumerate(train.stops):
            is_ls = stop.arrive.raw.strip().upper() == "LS"
            if is_ls:
                ls_total += 1
                if stop.arrive.value is not None:
                    ls_with_arrive.append(
                        {"train_no": train.train_no, "seq": stop.seq, "arrive": stop.arrive.value}
                    )
                if stop.arrive.value and stop.depart.value:
                    ls_with_two_times.append({"train_no": train.train_no, "seq": stop.seq})
                if not stop.depart.value:
                    ls_without_any_time.append({"train_no": train.train_no, "seq": stop.seq})
            elif not is_ls and index not in (0, len(train.stops) - 1):
                has_arrive = stop.arrive.value is not None
                has_depart = stop.depart.value is not None
                if has_depart and not has_arrive:
                    single_time_non_ls.append(
                        {
                            "train_no": train.train_no,
                            "seq": stop.seq,
                            "station": stop.station_code,
                            "depart": stop.depart.value,
                        }
                    )

    return {
        "ls_rows": ls_total,
        "ls_with_value_in_datang": ls_with_arrive,
        "ls_with_two_times": ls_with_two_times,
        "ls_without_any_time": ls_without_any_time,
        "non_ls_single_time_middle_rows": single_time_non_ls,
        "counter_example_count": (
            len(ls_with_arrive)
            + len(ls_with_two_times)
            + len(ls_without_any_time)
            + len(single_time_non_ls)
        ),
    }


def audit_cells(trains: list) -> dict:
    """Speed 0 vs '-', seconds precision, and footnote patterns."""
    speed_zero = 0
    speed_dash = 0
    speed_blank = 0
    seconds_total = 0
    seconds_non_zero = 0

    for train in trains:
        for stop in train.stops:
            raw = stop.speed.raw.strip()
            if raw == "0":
                speed_zero += 1
            elif raw == "-":
                speed_dash += 1
            elif raw == "":
                speed_blank += 1
            for cell in (stop.arrive, stop.depart):
                value = cell.value
                if value:
                    seconds_total += 1
                    if int(value.split(":")[2]) != 0:
                        seconds_non_zero += 1

    return {
        "speed_zero": speed_zero,
        "speed_dash": speed_dash,
        "speed_blank": speed_blank,
        "time_values": seconds_total,
        "non_zero_seconds": seconds_non_zero,
        "footnote_patterns": footnote_patterns(trains),
    }


# --- speed distribution -----------------------------------------------------


def speed_distribution(trains: list) -> dict:
    """Implied inter-station speeds. Reported before any threshold is chosen."""
    speeds: list[dict] = []
    per_train_max = []

    for train in trains:
        timed = []
        for stop in train.stops:
            reference = stop.depart.value or stop.arrive.value
            seconds = seconds_of(reference)
            if seconds is not None:
                timed.append((seconds, stop))

        train_speeds = []
        for (prev_s, _previous), (cur_s, _current) in zip(timed, timed[1:], strict=False):
            delta = cur_s - prev_s
            if delta <= 0:
                continue
            # A speed limit is printed per station; use the lower of the two as a
            # sanity reference only. No distance is known yet (Phase 4), so this
            # distribution is of DWELL+TRAVEL durations, not km/h.
            train_speeds.append(delta)
            speeds.append({"train_no": train.train_no, "seconds": delta})
        if train_speeds:
            per_train_max.append(max(train_speeds))

    values = sorted(s["seconds"] for s in speeds)
    if not values:
        return {"observations": 0}

    def quantile(q: float) -> int:
        index = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
        return values[index]

    return {
        "note": (
            "Durations between consecutive timed stops, not km/h: no distances are "
            "known until Phase 4. Thresholds for V2 are NOT chosen here."
        ),
        "observations": len(values),
        "min": values[0],
        "p05": quantile(0.05),
        "p25": quantile(0.25),
        "median": quantile(0.50),
        "p75": quantile(0.75),
        "p95": quantile(0.95),
        "p99": quantile(0.99),
        "max": values[-1],
        "under_30s": sum(1 for v in values if v < 30),
        "under_60s": sum(1 for v in values if v < 60),
        "over_4h": sum(1 for v in values if v > 4 * 3600),
        "longest": sorted(speeds, key=lambda s: -s["seconds"])[:10],
        "shortest": sorted(speeds, key=lambda s: s["seconds"])[:10],
    }


# --- gate -------------------------------------------------------------------


def quarantine_reasons(train) -> list[str]:
    """Reasons a train may not enter the validated layer."""
    reasons = []
    if train.completeness != COMPLETENESS_COMPLETE:
        reasons.append(f"completeness:{train.completeness}")
    if train.needs_review:
        reasons.extend(f"train:{r}" for r in train.needs_review)
    for stop in train.stops:
        reasons.extend(f"seq{stop.seq}:{r}" for r in stop.needs_review)
    return reasons


# --- review packs -----------------------------------------------------------


def _to_html(
    path: Path,
    title: str,
    trains: list[dict],
    pdf: Path,
    reports: list[dict] | None = None,
) -> None:
    images: dict[int, str] = {}
    pages = sorted({s["provenance"]["page"] for t in trains for s in t["stops"]})
    for page in pages:
        target = render_page_image(pdf, page, REVIEW_DIR)
        if target is not None:
            images[page] = f"{target.parent.name}/{target.name}"
    path.write_text(
        render_review_html(title, trains, reports or [], [], images=images),
        encoding="utf-8",
    )


def build_samples(trains: list[dict]) -> list[dict]:
    """A seeded random sample, stratified to include the hard cases."""
    picked: dict[str, dict] = {}

    def add_if(predicate, label: str) -> None:
        if any(t["_strata"] == label for t in picked.values()):
            return
        for train in trains:
            if predicate(train) and train["train_no"] not in picked:
                train = dict(train)
                train["_strata"] = label
                picked[train["train_no"]] = train
                return

    add_if(lambda t: len(t.get("loaded_pages", [])) > 1, "multi-page")
    add_if(lambda t: any(s["note"]["raw"] for s in t["stops"]), "with-footnote")
    add_if(
        lambda t: any(
            s[k]["value"] and int(s[k]["value"].split(":")[2]) != 0
            for s in t["stops"]
            for k in ("arrive", "depart")
        ),
        "non-zero-seconds",
    )
    add_if(lambda t: any(s["day_offset"] > 0 for s in t["stops"]), "midnight-crossing")
    add_if(lambda t: bool(t["needs_review"]), "has-needs-review")
    add_if(lambda t: any(s["needs_review"] for s in t["stops"]), "stop-needs-review")

    rng = random.Random(SAMPLE_SEED)
    remaining = [t for t in trains if t["train_no"] not in picked]
    for train in rng.sample(remaining, min(SAMPLE_SIZE - len(picked), len(remaining))):
        train = dict(train)
        train["_strata"] = "random"
        picked[train["train_no"]] = train

    return list(picked.values())


# --- report -----------------------------------------------------------------


def render_report(payload: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# Phase {payload['phase']} — {payload['title']}")
    add("")
    add("> Generated by `python -m pipeline.parse_intercity`. Do not edit by hand.")
    add("> Nothing here is described as *verified*; only the human spot-check does that.")
    add("")

    add("## Scope")
    add("")
    add(
        f"Subtype `{payload['subtype']}` only ({payload['scope_pages']} pages). "
        + payload["scope_note"]
    )
    add("")

    add("## Key numbers")
    add("")
    numbers = payload["numbers"]
    add("| Metric | Value |")
    add("|---|---|")
    for key, value in numbers.items():
        add(f"| {key} | {value} |")
    add("")

    add("## Completeness")
    add("")
    add("| Completeness | Trains |")
    add("|---|---|")
    for key, value in payload["completeness"].items():
        add(f"| {key} | {value} |")
    add("")

    add("## Quarantine reasons")
    add("")
    if payload["quarantine_reason_counts"]:
        add("| Reason | Trains |")
        add("|---|---|")
        for reason, count in payload["quarantine_reason_counts"].items():
            add(f"| `{reason}` | {count} |")
    else:
        add("None. Every parsed train passed the gate.")
    add("")

    add("## Validator results")
    add("")
    add("| Rule | Description | Result | Detail |")
    add("|---|---|---|---|")
    for row in payload["validators"]:
        add(f"| {row['rule']} | {row['description']} | {row['result']} | {row['detail']} |")
    add("")

    add("## Index reconciliation (V4)")
    add("")
    v4 = payload["v4"]
    add(f"- index train numbers: **{v4['index_numbers']}**")
    add(f"- parsed train numbers: **{v4['table_numbers']}**")
    add(f"- present in both: **{v4['in_both']}**")
    add(f"- in index, not parsed: **{len(v4['in_index_not_in_tables'])}**")
    add(f"- parsed, not in index: **{len(v4['in_tables_not_in_index'])}**")
    add(f"- page mismatches: **{v4['page_mismatch_count']}**")
    if not v4.get("index_has_page_column", True):
        add("")
        add(
            "**This book's index prints no page numbers**, so the page check "
            "cannot run. The index still supplies the set of train numbers."
        )
    add("")
    if v4["in_tables_not_in_index"]:
        add("Parsed but absent from the index: " + ", ".join(v4["in_tables_not_in_index"][:40]))
        add("")

    add("## Truncation")
    add("")
    truncated = payload["truncated_trains"]
    add(f"- truncated at the loaded page range: **{len(truncated)}**")
    if truncated:
        add("Truncated trips never enter `data/validated/`; they are quarantined and listed here.")
        add("")
        add("| Train | Last station | Destination |")
        add("|---|---|---|")
        for item in truncated[:40]:
            add(f"| {item['train_no']} | {item['last_station']} | {item['destination']} |")
    add("")
    add("All other trips reach their destination inside the loaded pages.")
    add("")

    add("## service_class (joined by train number)")
    add("")
    add(payload["service_class"]["note"])
    add("")
    add("| Class | Trains |")
    add("|---|---|")
    for key, value in payload["service_class"]["class_counts"].items():
        add(f"| {key} | {value} |")
    add("")
    add(f"- matched by train number: **{payload['service_class']['matched']}**")
    add(f"- unmatched: **{payload['service_class']['unmatched_count']}**")
    add(f"- conflicting summary rows: **{len(payload['service_class']['conflicting'])}**")
    add("")

    add("## V10 — untimed pass rows")
    add("")
    v10 = payload["v10"]
    add(f"- rows checked: **{v10['checked']}**")
    add(f"- findings: **{v10['finding_count']}**")
    add(f"- trains with at least one untimed pass row: **{len(v10['counts_by_train'])}**")
    add("")
    add(
        "Untimed pass rows must sit strictly between two timed rows. The Phase 5 "
        "engine estimates them by distance-proportional interpolation; the parsed "
        "layer never stores a fabricated time."
    )
    add("")
    if v10["counts_by_train"]:
        add("| Train | Untimed pass rows |")
        add("|---|---|")
        for train_no, count in list(v10["counts_by_train"].items())[:20]:
            add(f"| {train_no} | {count} |")
        add("")

    add("## V11 — sequence continuity")
    add("")
    v11 = payload["v11"]
    add(f"- rows checked: **{v11['checked']}**")
    add(f"- findings: **{v11['finding_count']}**")
    add("")
    if v11["findings"]:
        add("| Train | Seq | Detail |")
        add("|---|---|---|")
        for finding in v11["findings"][:40]:
            add(f"| {finding['train_no']} | {finding['seq']} | {finding['detail']} |")
        add("")
    else:
        add("Every train prints No. 1..N with no gaps and no duplicates.")
        add("")

    add("## Pass-row semantics")
    add("")
    pass_rows = payload["pass_rows"]
    add(f"- `Ls` rows: **{pass_rows['ls_rows']}**")
    add(f"- `Ls` with a value in Datang: **{len(pass_rows['ls_with_value_in_datang'])}**")
    add(f"- `Ls` with two times: **{len(pass_rows['ls_with_two_times'])}**")
    add(f"- `Ls` with no time at all: **{len(pass_rows['ls_without_any_time'])}**")
    add(
        f"- non-`Ls` middle rows with a single (depart) time: "
        f"**{len(pass_rows['non_ls_single_time_middle_rows'])}**"
    )
    add("")

    add("## Cell conventions")
    add("")
    cells = payload["cells"]
    add(f"- speed `0`: **{cells['speed_zero']}**")
    add(f"- speed `-`: **{cells['speed_dash']}**")
    add(f"- speed blank: **{cells['speed_blank']}**")
    add(f"- time values: **{cells['time_values']}**")
    add(
        f"- with non-zero seconds: **{cells['non_zero_seconds']}** "
        f"({cells['non_zero_seconds'] / cells['time_values']:.1%})"
        if cells["time_values"]
        else "- with non-zero seconds: 0"
    )
    add("")

    add("## Distinct Keterangan / footnote patterns")
    add("")
    if cells["footnote_patterns"]:
        add("| Pattern (verbatim) | Count |")
        add("|---|---|")
        for pattern in cells["footnote_patterns"]:
            add(f"| `{pattern['text']}` | {pattern['count']} |")
    else:
        add("None found.")
    add("")

    add("## Timing distribution (V2 evidence)")
    add("")
    speed = payload["speed"]
    if speed.get("observations"):
        add("| Metric | Seconds |")
        add("|---|---|")
        for key in ("observations", "min", "p05", "p25", "median", "p75", "p95", "p99", "max"):
            add(f"| {key} | {speed[key]} |")
        add(f"| under 30s | {speed['under_30s']} |")
        add(f"| under 60s | {speed['under_60s']} |")
        add(f"| over 4h | {speed['over_4h']} |")
        add("")
        add(speed["note"])
    else:
        add("No timed segments.")
    add("")

    add("## Runtime")
    add("")
    add(f"- parse + validate: **{payload['runtime_seconds']:.1f}s**")
    add(f"- pages in scope: **{payload['scope_pages']}**")
    add("")

    add("## Known limitations")
    add("")
    for limitation in payload["limitations"]:
        add(f"- {limitation}")
    add("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2a: full intercity Book 1.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--book",
        choices=["1", "2"],
        default="1",
        help="1 = intercity (default), 2 = local",
    )
    args = parser.parse_args(argv)

    started = time.time()
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATED_DIR.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    subtype = BOOK1_SUBTYPE if args.book == "1" else BOOK2_SUBTYPE
    slug = "intercity" if args.book == "1" else "local"
    pages = pages_for_subtype(subtype)
    if args.limit:
        pages = pages[: args.limit]

    trains, parsed_pages = parse_book1(args.pdf, pages)
    train_dicts = [t.as_dict() for t in trains]

    (PARSED_DIR / f"{slug}_trips.json").write_text(
        json.dumps(
            {
                "verified_by_human": False,
                "scope": "intercity Book 1",
                "pages_parsed": len(parsed_pages),
                "trains": train_dicts,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # --- index for V4 ---
    index_path = PARSED_DIR / (
        "expected_trains_intercity.json" if args.book == "1" else "expected_trains_local.json"
    )
    index_entries = (
        json.loads(index_path.read_text(encoding="utf-8"))["entries"] if index_path.exists() else []
    )
    # Book 2's index prints no page numbers at all, so only book 1 has a usable
    # offset table. Passing an empty table keeps the page check honest (it simply
    # cannot run) instead of fabricating a mapping.
    offset_table = [(58, 664, 57), (670, 811, 669)] if args.book == "1" else []

    v1 = validate_v1(trains)
    v2 = validate_v2(trains)
    v4 = validate_v4(trains, index_entries, offset_table)
    v8 = validate_v8(trains)
    v9 = validate_v9(trains)
    v10 = validate_v10(trains)
    v11 = validate_v11(trains)

    # service_class join (by train number, never from the F suffix)
    class_index = build_index()
    class_report = join_service_class(train_dicts, class_index)

    # --- gate ---
    validated: list[dict] = []
    quarantined: list[dict] = []
    v1_failed = {v.train_no for v in v1.violations}
    v2_failed = {v.train_no for v in v2.violations}
    v8_failed = {r["train_no"] for r in v8["violations"]}
    v10_failed = {f.train_no for f in v10.findings}
    v11_failed = {f.train_no for f in v11.findings}

    for train, payload in zip(trains, train_dicts, strict=True):
        reasons = quarantine_reasons(train)
        if train.train_no in v1_failed:
            reasons.append("V1:time_not_monotonic")
        if train.train_no in v2_failed:
            reasons.append("V2:travel_time_out_of_bounds")
        if train.train_no in v8_failed:
            reasons.append("V8:endpoint_mismatch")
        if train.train_no in v10_failed:
            reasons.append("V10:untimed_pass_row_at_edge")
        if train.train_no in v11_failed:
            reasons.append("V11:sequence_discontinuity")
        if reasons:
            quarantined.append({"train_no": train.train_no, "reasons": reasons, "payload": payload})
        else:
            validated.append(payload)

    (QUARANTINE_DIR / f"{slug}_book{args.book}.json").write_text(
        json.dumps(
            {
                "note": "Reason codes only; no train is hand-fixed.",
                "count": len(quarantined),
                "trains": [
                    {"train_no": q["train_no"], "reasons": q["reasons"]} for q in quarantined
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (VALIDATED_DIR / f"{slug}_book{args.book}.json").write_text(
        json.dumps(
            {
                "verified_by_human": False,
                "gate": "completeness==complete, V1, V2, V8 pass, zero needs_review",
                "count": len(validated),
                "trains": validated,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # --- review packs ---
    # Mark quarantined trains so a sample never looks like validated data (C4).
    quarantine_reason_by_no = {q["train_no"]: q["reasons"] for q in quarantined}
    review_trains = []
    for train in train_dicts:
        copy = dict(train)
        reasons = quarantine_reason_by_no.get(train["train_no"])
        copy["quarantined"] = bool(reasons)
        copy["quarantine_reasons"] = reasons or []
        review_trains.append(copy)

    _to_html(
        REVIEW_DIR / f"{slug}_sample.html",
        "Phase 2a — stratified sample (25 trains)",
        build_samples(review_trains),
        args.pdf,
    )
    _to_html(
        REVIEW_DIR / f"{slug}_needs_review.html",
        "Phase 2a — every needs_review item and every quarantined train",
        [
            t
            for t in review_trains
            if t["quarantined"]
            or t["needs_review"]
            or any(stop["needs_review"] for stop in t["stops"])
        ],
        args.pdf,
    )

    # --- report payload ---
    # Reason codes are "train:<reason>" or "seq<N>:<reason>" or "V1:...". Report
    # the REASON, not the location prefix, so the table is readable.
    def reason_code(reason: str) -> str:
        head, _, tail = reason.partition(":")
        if head.startswith("seq") or head == "train":
            return tail or head
        return reason

    # Count distinct trains per reason (a train may repeat one reason at many
    # sequences), which is what a reviewer needs.
    per_reason: Counter[str] = Counter()
    for q in quarantined:
        for code in {reason_code(r) for r in q["reasons"]}:
            per_reason[code] += 1
    reason_counts = per_reason
    completeness = Counter(t.completeness for t in trains)

    numbers = {
        "trains parsed": len(train_dicts),
        "stops parsed": sum(len(t["stops"]) for t in train_dicts),
        "validated": len(validated),
        "quarantined": len(quarantined),
        "pages in scope": len(pages),
        "pages parsed": len(parsed_pages),
    }

    payload = {
        "phase": "2a" if args.book == "1" else "2b",
        "title": "Intercity Book 1" if args.book == "1" else "Local Book 2",
        "subtype": subtype,
        "scope_note": (
            "Book 2 (local), KRL, and freight are out of scope."
            if args.book == "1"
            else "Book 1 (intercity), KRL, and freight are out of scope."
        ),
        "book": args.book,
        "scope_pages": len(pages),
        "numbers": numbers,
        "completeness": dict(completeness),
        "quarantine_reason_counts": dict(reason_counts),
        "validators": [
            {
                "rule": "V1",
                "description": v1.description,
                "result": "PASS" if v1.passed else "FAIL",
                "detail": f"{v1.checked} checks, {len(v1.violations)} violations",
            },
            {
                "rule": "V2",
                "description": v2.description,
                "result": "PASS" if v2.passed else "FAIL",
                "detail": f"{v2.checked} checks, {len(v2.violations)} violations",
            },
            {
                "rule": "V4",
                "description": v4["description"],
                "result": "INFO",
                "detail": (
                    f"{v4['in_both']} matched, "
                    f"{len(v4['in_tables_not_in_index'])} parsed-not-in-index"
                ),
            },
            {
                "rule": "V8",
                "description": v8["description"],
                "result": "PASS" if not v8["violations"] else "FAIL",
                "detail": (
                    f"{v8['passed']} passed, {len(v8['violations'])} failed, "
                    f"{v8['reported_not_checked']} reported not checked"
                ),
            },
            {
                "rule": "V9",
                "description": v9["description"],
                "result": "INFO",
                "detail": (
                    f"{v9['segments']} pairs, {v9['single_train_pair_count']} single-train, "
                    f"{v9['outlier_count']} outliers"
                ),
            },
            {
                "rule": "V10",
                "description": v10.description,
                "result": "PASS" if v10.passed else "FAIL",
                "detail": (
                    f"{v10.checked} rows, {len(v10.findings)} findings, "
                    f"{len(v10.counts_by_train)} trains with untimed pass rows"
                ),
            },
            {
                "rule": "V11",
                "description": v11.description,
                "result": "PASS" if v11.passed else "FAIL",
                "detail": f"{v11.checked} rows, {len(v11.findings)} findings",
            },
        ],
        "v4": v4,
        "truncated_trains": [
            {
                "train_no": train_dict["train_no"],
                "last_station": train_dict["stops"][-1]["station_code"]
                if train_dict["stops"]
                else None,
                "destination": train_dict["destination"],
            }
            for train_dict in train_dicts
            if train_dict["completeness"] == "truncated_at_loaded_pages"
        ],
        "service_class": class_report,
        "v10": v10.as_dict(),
        "v11": v11.as_dict(),
        "pass_rows": audit_pass_rows(trains),
        "cells": audit_cells(trains),
        "speed": speed_distribution(trains),
        "runtime_seconds": time.time() - started,
        "limitations": [
            (
                "Only Book 1 is parsed. Book 2 (local), KRL, and freight are untouched."
                if args.book == "1"
                else "Only Book 2 is parsed. Book 1, KRL, and freight are untouched."
            ),
            "V9 reports single-train pairs as *possible* misread station order; "
            "it cannot confirm one.",
            "V2 thresholds are not chosen here; the distribution above is the evidence "
            "for choosing them.",
            "Durations are between timed stops, not km/h, because distances arrive in Phase 4.",
            "Truncated trips cannot satisfy V8's destination check and are quarantined.",
            "No calendar information exists in the PDF (ADR 002), so no "
            "operating-day logic is exercised.",
            "service_class is joined by train number; a trip whose number is absent "
            "from Lampiran IV stays unknown rather than being guessed.",
            "V2 keeps only the hard gates (time > 0, monotonic). Speed thresholds "
            "need Phase 4 distances and are deferred.",
        ],
    }

    report_path = DOCS / ("phase2a_report.md" if args.book == "1" else "phase2b_report.md")
    report_path.write_text(render_report(payload), encoding="utf-8")
    (REVIEW_DIR / f"phase{args.book}_v9.json").write_text(
        json.dumps(v9, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (REVIEW_DIR / f"phase{args.book}_v4.json").write_text(
        json.dumps(v4, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"pages in scope: {len(pages)}  parsed: {len(parsed_pages)}")
    print(f"trains: {len(train_dicts)}  stops: {numbers['stops parsed']}")
    print(f"validated: {len(validated)}  quarantined: {len(quarantined)}")
    print(f"completeness: {dict(completeness)}")
    print(
        f"V1 {'PASS' if v1.passed else 'FAIL'}  V2 {'PASS' if v2.passed else 'FAIL'}  "
        f"V8 {'PASS' if not v8['violations'] else 'FAIL'}"
    )
    print(
        f"V4: {v4['in_both']} matched, {len(v4['in_tables_not_in_index'])} parsed-not-in-index, "
        f"{v4['page_mismatch_count']} page mismatches"
    )
    print(
        f"pass rows: {payload['pass_rows']['ls_rows']} Ls, "
        f"{payload['pass_rows']['counter_example_count']} counter-examples"
    )
    print(f"runtime: {payload['runtime_seconds']:.1f}s")
    print(f"wrote {report_path}")
    return 0 if not v1.violations and not v2.violations else 1


if __name__ == "__main__":
    sys.exit(main())
