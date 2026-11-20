"""Station-name conflicts: where each code appears, listed never resolved.

Resolution is deferred to Phase 3. This module only records evidence.

Usage:
    python -m pipeline.station_conflicts
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.station_codes import (
    STATION_ROW_RE,
    _normalise_name,
    near_duplicates,
    prefix_pairs,
    scan_words_dir,
)

DEFAULT_WORDS = Path("data/raw/words")
DEFAULT_OUT = Path("data/review/station_name_conflicts.json")


def collect_occurrences(words_dir: Path) -> dict:
    """For each station code: pages, name spellings, and occurrence counts."""
    occurrences: dict[str, dict] = defaultdict(
        lambda: {"pages": set(), "names": Counter(), "occurrences": 0}
    )

    for path in sorted(words_dir.glob("page_*.json")):
        page = int(path.stem.split("_")[1])
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows: dict[int, list] = {}
        for word in payload["words"]:
            rows.setdefault(round(word[1] / 3), []).append(word)
        for key in sorted(rows):
            line = " ".join(w[4] for w in sorted(rows[key], key=lambda w: w[0]))
            match = STATION_ROW_RE.match(line)
            if not match:
                continue
            name = _normalise_name(match.group(2))
            code = match.group(3)
            entry = occurrences[code]
            entry["pages"].add(page)
            entry["names"][name] += 1
            entry["occurrences"] += 1

    return occurrences


def _shrink(occurrence: dict) -> dict:
    pages = sorted(occurrence["pages"])
    return {
        "pages_count": len(pages),
        "pages": pages,
        "occurrences": occurrence["occurrences"],
        "names": dict(occurrence["names"]),
    }


def build_report(words_dir: Path = DEFAULT_WORDS) -> dict:
    index = scan_words_dir(words_dir)
    occurrences = collect_occurrences(words_dir)

    names = set(index.name_to_codes)
    duplicates = near_duplicates(names)
    prefixes = prefix_pairs(names)

    code_conflicts = {
        code: sorted(spellings)
        for code, spellings in sorted(index.code_to_names.items())
        if len(spellings) > 1
    }
    name_conflicts = {
        name: sorted(codes) for name, codes in sorted(index.name_to_codes.items()) if len(codes) > 1
    }

    return {
        "status": "resolution deferred to Phase 3; nothing here is resolved",
        "note": (
            "Evidence only. Two codes printing the same name may be two distinct "
            "stations on different lines, or one station printed inconsistently. "
            "A human decides."
        ),
        "codes_total": len(index.code_to_names),
        "names_total": len(index.name_to_codes),
        "name_to_multiple_codes": {
            name: {
                "codes": codes,
                "per_code": {
                    code: _shrink(occurrences[code]) if code in occurrences else None
                    for code in codes
                },
            }
            for name, codes in name_conflicts.items()
        },
        "code_to_multiple_names": {
            code: {
                "names": spellings,
                "occurrence": _shrink(occurrences[code]) if code in occurrences else None,
            }
            for code, spellings in code_conflicts.items()
        },
        "near_duplicate_pairs": [
            {
                "a": a,
                "b": b,
                "codes_a": sorted(index.name_to_codes[a]),
                "codes_b": sorted(index.name_to_codes[b]),
                "occurrences_a": {
                    c: _shrink(occurrences[c])["pages_count"]
                    for c in sorted(index.name_to_codes[a])
                    if c in occurrences
                },
                "occurrences_b": {
                    c: _shrink(occurrences[c])["pages_count"]
                    for c in sorted(index.name_to_codes[b])
                    if c in occurrences
                },
            }
            for a, b in duplicates
        ],
        "prefix_pairs": [
            {
                "shorter": a,
                "longer": b,
                "codes_shorter": sorted(index.name_to_codes[a]),
                "codes_longer": sorted(index.name_to_codes[b]),
                "pages_shorter": {
                    c: _shrink(occurrences[c])["pages_count"]
                    for c in sorted(index.name_to_codes[a])
                    if c in occurrences
                },
                "pages_longer": {
                    c: _shrink(occurrences[c])["pages_count"]
                    for c in sorted(index.name_to_codes[b])
                    if c in occurrences
                },
            }
            for a, b in prefixes
        ],
        "counts": {
            "name_to_multiple_codes": len(name_conflicts),
            "code_to_multiple_names": len(code_conflicts),
            "near_duplicate_pairs": len(duplicates),
            "prefix_pairs": len(prefixes),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report station-name conflicts.")
    parser.add_argument("--words", type=Path, default=DEFAULT_WORDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    report = build_report(args.words)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"counts: {report['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
