"""Parse the validity date printed on every divider page.

Each train-series divider carries one line: ``Berlaku Mulai Tanggal 01 Desember
2026``. This module extracts it from every divider and checks whether all of them
agree. Report only.

Usage:
    python -m pipeline.validity
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DEFAULT_WORDS = Path("data/raw/words")
DEFAULT_OUT = Path("data/review/validity_dates.json")

MONTHS = {
    "JANUARI": 1,
    "FEBRUARI": 2,
    "MARET": 3,
    "APRIL": 4,
    "MEI": 5,
    "JUNI": 6,
    "JULI": 7,
    "AGUSTUS": 8,
    "SEPTEMBER": 9,
    "OKTOBER": 10,
    "NOVEMBER": 11,
    "DESEMBER": 12,
}

VALIDITY_RE = re.compile(r"BERLAKU\s+MULAI\s+TANGGAL\s+(\d{1,2})\s+([A-Z]+)\s+(\d{4})")


def parse_date(text: str) -> str | None:
    match = VALIDITY_RE.search(text.upper())
    if not match:
        return None
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name)
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def collect(words_dir: Path) -> dict:
    """Find every page that states a validity date."""
    hits: list[dict] = []
    divider_pages: list[int] = []

    for path in sorted(words_dir.glob("page_*.json")):
        page = int(path.stem.split("_")[1])
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = " ".join(row[4] for row in payload["words"])
        upper = " ".join(text.upper().split())

        if "DAFTAR WAKTU" in upper and "ISI:" in upper:
            divider_pages.append(page)

        iso = parse_date(upper)
        if iso is not None:
            hits.append({"page": page, "effective_from": iso, "is_divider": page in divider_pages})

    dates = sorted({hit["effective_from"] for hit in hits})
    divider_dates = sorted({hit["effective_from"] for hit in hits if hit["is_divider"]})
    dividers_without_date = [
        page for page in divider_pages if not any(hit["page"] == page for hit in hits)
    ]

    return {
        "note": (
            "Validity start only. The PDF states no validity end date and no "
            "weekday pattern (ADR 002)."
        ),
        "pages_with_validity_line": len(hits),
        "divider_pages": len(divider_pages),
        "distinct_dates": dates,
        "distinct_dates_on_dividers": divider_dates,
        "all_agree": len(dates) == 1,
        "dividers_without_a_date": dividers_without_date,
        "proposed_effective_from": dates[0] if len(dates) == 1 else None,
        "proposed_effective_to": None,
        "hits": hits,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract validity dates from dividers.")
    parser.add_argument("--words", type=Path, default=DEFAULT_WORDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    report = collect(args.words)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"pages with a validity line: {report['pages_with_validity_line']}")
    print(f"divider pages: {report['divider_pages']}")
    print(f"distinct dates: {report['distinct_dates']}")
    print(f"all agree: {report['all_agree']}")
    print(f"dividers without a date: {len(report['dividers_without_a_date'])}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
