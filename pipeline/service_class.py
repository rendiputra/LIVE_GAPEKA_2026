"""Join service_class (reguler | fakultatif | unknown) onto trips.

The class comes from the Lampiran IV summary tables, joined **by train number**.
It is never derived from the ``F`` suffix (ADR 002 / human ruling), even though
the two currently agree perfectly.

Multi-number trips are reported, not silently matched: the join records which
constituent number produced the class and whether every constituent agreed.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DEFAULT_SUMMARY = Path("data/parsed/summary_tables_lampiran_iv.json")

CATEGORY_TO_CLASS = {
    "REGULER": "reguler",
    "FAKULTATIF": "fakultatif",
}


def split_numbers(text: str | None) -> list[str]:
    """Split a multi-train row, but never a locomotive series (L2724F-1)."""
    import re

    plain = re.compile(r"^\d{1,4}[A-Z]?$")
    if not text:
        return []
    parts = text.split("-")
    if len(parts) > 1 and all(plain.match(part) for part in parts):
        return parts
    return [text]


def build_index(summary_path: Path = DEFAULT_SUMMARY) -> dict:
    """train_no -> set of service classes seen in the summary tables."""
    if not summary_path.exists():
        return {}
    entries = json.loads(summary_path.read_text(encoding="utf-8"))
    index: dict[str, set[str]] = {}
    for entry in entries:
        category = (entry.get("category") or "").upper()
        service_class = CATEGORY_TO_CLASS.get(category)
        if service_class is None:
            continue
        for number in split_numbers(entry.get("train_no")):
            index.setdefault(number, set()).add(service_class)
    return index


def join(trains: list[dict], index: dict) -> dict:
    """Attach ``service_class`` + provenance to every trip."""
    matched = 0
    unmatched: list[str] = []
    conflicting: list[dict] = []
    multi_reports: list[dict] = []
    class_counts: Counter[str] = Counter()

    for train in trains:
        numbers = split_numbers(train.get("train_no"))
        found: dict[str, list[str]] = {}
        for number in numbers:
            if number in index:
                found[number] = sorted(index[number])

        if len(numbers) > 1:
            multi_reports.append(
                {
                    "train_no": train.get("train_no"),
                    "constituents": numbers,
                    "matched_constituents": found,
                    "method": "class taken from the first constituent that matched",
                }
            )

        if not found:
            train["service_class"] = "unknown"
            train["service_class_source"] = "no_summary_match"
            unmatched.append(train.get("train_no") or "?")
            class_counts["unknown"] += 1
            continue

        classes = {value for values in found.values() for value in values}
        if len(classes) > 1:
            train["service_class"] = "unknown"
            train["service_class_source"] = "conflicting_summary_rows"
            conflicting.append(
                {
                    "train_no": train.get("train_no"),
                    "per_constituent": found,
                    "classes": sorted(classes),
                }
            )
            class_counts["unknown"] += 1
            continue

        service_class = classes.pop()
        first = numbers[0] if numbers else None
        train["service_class"] = service_class
        train["service_class_source"] = f"lampiran_iv_summary:train_no={first}"
        matched += 1
        class_counts[service_class] += 1

    return {
        "note": (
            "service_class is joined BY TRAIN NUMBER from the Lampiran IV summary "
            "tables. It is never derived from the F suffix."
        ),
        "matched": matched,
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
        "conflicting": conflicting,
        "multi_number_trains": multi_reports,
        "class_counts": dict(class_counts),
    }
