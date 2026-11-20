"""Write the Lampiran IV classification report (Q1c evidence).

Usage:
    python -m pipeline.summary_report
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.summary_tables import f_suffix_analysis, parse_summary

DEFAULT_WORDS = Path("data/raw/words")
DEFAULT_OUT = Path("data/review/f_suffix_evidence.json")
DEFAULT_PARSED = Path("data/parsed/summary_tables_lampiran_iv.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REGULER/FAKULTATIF vs F suffix.")
    parser.add_argument("--words", type=Path, default=DEFAULT_WORDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--parsed", type=Path, default=DEFAULT_PARSED)
    args = parser.parse_args(argv)

    entries = parse_summary(args.words)
    analysis = f_suffix_analysis(entries)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    analysis["history"] = [
        {
            "note": (
                "An earlier parse reported 2,127 entries / 2,391 distinct numbers. "
                "That was a parser defect, not a document difference: page 1829 "
                "stacks two summary tables, and the page's classification block "
                "displaced the train number of the rows between them. Fixed by "
                "anchoring rows on the sequence column and dropping header "
                "furniture per row. Current figures supersede it."
            ),
        }
    ]
    args.out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.parsed.parent.mkdir(parents=True, exist_ok=True)
    args.parsed.write_text(
        json.dumps([e.as_dict() for e in entries], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"summary entries: {analysis['summary_entries']}")
    print(f"distinct train numbers: {analysis['distinct_train_numbers']}")
    print(f"categories: {analysis['category_counts']}")
    print(f"numbers with an F: {analysis['numbers_with_f_suffix']}")
    print(f"F and FAKULTATIF: {analysis['suffix_and_fakultatif']}")
    print(f"F but not FAKULTATIF: {len(analysis['suffix_but_not_fakultatif'])}")
    print(f"FAKULTATIF without F: {len(analysis['fakultatif_without_suffix'])}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
