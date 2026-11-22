"""F4: audit station name spacing.

Some official names are printed run-together ("Bekasitimur"). This reports every
candidate; it does NOT invent a spaced form. A name is only ever changed by the
human in `station_aliases.yaml`.

Detection is deliberately conservative: a name is a candidate when it has no
space, is long enough that a concatenation is plausible, and its lowercased
substring can be split into two dictionary words drawn from the station
vocabulary elsewhere in the data.

Usage:
    python -m pipeline.station_spacing
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/gapeka.db")
ALIASES = Path("data/config/station_aliases.yaml")
OUT = Path("data/review/station_spacing.json")

MIN_PART = 3


def _vocabulary(names: list[str]) -> set[str]:
    """Words the data itself proves: every part AND every whole station name.

    Using whole names is what lets "Surabayakota" split on "Surabaya" + "kota"
    without importing outside knowledge. A word that appears ONLY inside the
    run-together name (e.g. "timur" in "Bekasitimur") is not evidence, so such a
    name lands in the review list instead of the suggested list.
    """
    words: set[str] = set()
    for name in names:
        cleaned = name.replace("-", " ").strip()
        if not cleaned:
            continue
        words.add(cleaned.casefold())
        for part in cleaned.split():
            if len(part) >= MIN_PART:
                words.add(part.casefold())
    return words


def _split_candidates(name: str, vocabulary: set[str]) -> list[tuple[str, str]]:
    """Every way to split a run-together name into two known words."""
    out = []
    lowered = name.casefold()
    for index in range(MIN_PART, len(name) - MIN_PART + 1):
        left, right = lowered[:index], lowered[index:]
        if left in vocabulary and right in vocabulary:
            out.append((name[:index], name[index:]))
    return out


def audit() -> dict:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT code, name, official_name FROM stations ORDER BY code"
        ).fetchall()
    finally:
        connection.close()

    names = [(row[2] or row[1] or "").strip() for row in rows]
    vocabulary = _vocabulary(names)

    whole_names = {
        name.casefold(): code
        for code, printed, official in rows
        for name in [(official or printed or "").strip()]
        if name
    }

    def prefix_matches(name: str) -> list[str]:
        """Other station names that are a prefix of this one.

        "Bekasitimur" starts with the station name "Bekasi", which is evidence of
        concatenation that needs no outside knowledge.
        """
        lowered = name.casefold()
        return sorted(
            other
            for other in whole_names
            if len(other) >= 4 and other != lowered and lowered.startswith(other)
        )

    suggested = []
    review = []
    for code, printed, official in rows:
        display = (official or printed or "").strip()
        if not display or " " in display or "-" in display:
            continue
        if len(display) < MIN_PART * 2:
            continue
        splits = _split_candidates(display, vocabulary)
        entry = {
            "code": code,
            "name": display,
            "pdf_name": printed,
            "official_name": official,
            "in_aliases": official is not None,
        }
        if splits:
            suggested.append(
                {**entry, "split_candidates": [f"{left} {right}" for left, right in splits]}
            )
        elif len(display) >= 10:
            # Long enough that a concatenation is plausible, but the data cannot
            # prove where it splits. Listed, never changed.
            entry["prefix_matches"] = prefix_matches(display)
            review.append(entry)

    # Most actionable first: a name that starts with another station's name.
    review.sort(key=lambda row: (not row.get("prefix_matches"), row["code"]))

    return {
        "note": (
            "F4 report only. 'suggested' names split into two words the data itself "
            "proves (other station names or their parts). 'review' names are "
            "run-together and long, but the data cannot prove a split, so they need "
            "a human eye. Nothing is renamed: a spacing fix requires the PDF or "
            "station_aliases.yaml to carry the spaced form."
        ),
        "stations": len(rows),
        "suggested": suggested,
        "review": review,
        "suggested_count": len(suggested),
        "review_count": len(review),
    }


def main() -> int:
    payload = audit()
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(
        f"  stations {payload['stations']}, suggested {payload['suggested_count']}, "
        f"review {payload['review_count']}"
    )
    for row in payload["suggested"]:
        print(f"    SUGGEST {row['code']:5s} {row['name']:24s} -> {row['split_candidates']}")
    for row in payload["review"]:
        print(f"    REVIEW  {row['code']:5s} {row['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
