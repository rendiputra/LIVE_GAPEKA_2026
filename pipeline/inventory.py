"""Phase 0 inventory: classify every page of the Gapeka PDF.

Deterministic by construction: no clock, no randomness, no network. Re-running
on the same PDF produces byte-identical output (ADR 001).

Usage:
    python -m pipeline.inventory --pdf data/input/GAPEKA_2026.pdf
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import pymupdf

from pipeline.classify import (
    PAGE_TYPES,
    SECTIONS,
    PageSignals,
    assign_sections,
    classify_page,
    derive_subtype,
)

DEFAULT_PDF = Path("data/input/GAPEKA_2026.pdf")
DEFAULT_OUT = Path("data/raw/inventory.json")
DEFAULT_REPORT = Path("docs/inventory_report.md")

SCHEMA_VERSION = 1

# Printed page numbers sit in the page margin: a bare number, or a roman-prefixed
# number such as "II-2" on the stringline annex.
PRINTED_PAGE_RE = re.compile(r"^(\d{1,4}|[IVX]+-\d+)$")
MARGIN_FRACTION = 0.10

# Header patterns used to estimate the train count. They are deliberately
# different shapes so the report can show how much the estimate depends on them.
TRAIN_HEADER_RE = re.compile(
    r"KA\s+(\d+[A-Z]?)\s*\(([^)]*)\)\s*RELASI\s+([A-Z0-9]+)\s*-\s*([A-Z0-9]+)"
)
TRAIN_ANY_RE = re.compile(r"KA\s+(\d+[A-Z]?)\s*\(")
TRAIN_LINTAS_RE = re.compile(r"KA\s+(\d+[A-Z]?)\s*\(([^)]*)\)\s*LINTAS PELAYANAN")


def normalise(text: str) -> str:
    return " ".join(text.upper().split())


def extract_printed_page(words: list[tuple], height: float) -> str | None:
    """Find the printed page number in the top or bottom margin.

    The number is a bare token alone on its own text line, so table cells that
    happen to be numbers are rejected. Bottom margin is checked first; the
    stringline annex prints its number at the top instead.
    """
    for region in ("bottom", "top"):
        if region == "bottom":
            selected = [w for w in words if w[1] > height * (1 - MARGIN_FRACTION)]
        else:
            selected = [w for w in words if w[3] < height * MARGIN_FRACTION]

        lines: dict[int, list[tuple]] = {}
        for w in selected:
            lines.setdefault(round(w[1] / 3), []).append(w)

        candidates = [
            group
            for group in lines.values()
            if len(group) == 1 and PRINTED_PAGE_RE.match(group[0][4].strip())
        ]
        if candidates:
            candidates.sort(key=lambda g: g[0][1], reverse=(region == "bottom"))
            return candidates[0][0][4].strip()

    return None


def extract_signals(doc: pymupdf.Document, index: int) -> PageSignals:
    page = doc[index]
    raw_text = page.get_text("text")
    words = page.get_text("words")
    text = normalise(raw_text)

    return PageSignals(
        page=index + 1,
        width_pt=round(page.rect.width, 2),
        height_pt=round(page.rect.height, 2),
        rotation=page.rotation,
        word_count=len(words),
        image_count=len(page.get_images(full=True)),
        text=text,
        time_token_count=len(re.findall(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", text)),
        table_header_count=text.count("STASIUN DAN PERHENTIAN"),
        train_header_count=len(TRAIN_HEADER_RE.findall(text)),
        train_any_count=len(TRAIN_ANY_RE.findall(text)),
        train_lintas_count=len(TRAIN_LINTAS_RE.findall(text)),
        printed_page=extract_printed_page(words, page.rect.height),
    )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(pdf_path: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    try:
        signals = [extract_signals(doc, i) for i in range(doc.page_count)]
        sections = assign_sections(signals)

        relasi_numbers: set[str] = set()
        lintas_numbers: set[str] = set()

        pages = []
        for s, section in zip(signals, sections, strict=True):
            classification = classify_page(s)
            # Count train numbers only on the page types that legitimately list
            # them, so divider pages do not inflate the estimate.
            if classification.type == "train_table":
                relasi_numbers.update(m[0] for m in TRAIN_HEADER_RE.findall(s.text))
            if classification.type == "line_table":
                lintas_numbers.update(m[0] for m in TRAIN_LINTAS_RE.findall(s.text))
            pages.append(
                {
                    "page": s.page,
                    "rotation": s.rotation,
                    "width_pt": s.width_pt,
                    "height_pt": s.height_pt,
                    "orientation": s.orientation,
                    "word_count": s.word_count,
                    "image_count": s.image_count,
                    "time_token_count": s.time_token_count,
                    "time_density": round(s.time_density, 4),
                    "table_header_count": s.table_header_count,
                    "train_header_count": s.train_header_count,
                    "train_any_count": s.train_any_count,
                    "train_lintas_count": s.train_lintas_count,
                    "text_extractable": s.word_count > 0,
                    "printed_page": s.printed_page,
                    "type": classification.type,
                    "subtype": derive_subtype(classification.type, section, s),
                    "section": section,
                    "confidence": classification.confidence,
                    "rule": classification.rule,
                    "reasons": list(classification.reasons),
                }
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "path": str(pdf_path),
                "sha256": sha256_of(pdf_path),
                "size_bytes": pdf_path.stat().st_size,
                "page_count": doc.page_count,
            },
            "tool": {
                "pymupdf": pymupdf.version[1],
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            },
            "pages": pages,
            "summary": summarise(pages, relasi_numbers, lintas_numbers),
        }
    finally:
        doc.close()


def summarise(
    pages: list[dict],
    relasi_numbers: set[str] | None = None,
    lintas_numbers: set[str] | None = None,
) -> dict:
    by_type = {t: 0 for t in PAGE_TYPES}
    by_section = {s: 0 for s in SECTIONS}
    by_confidence: dict[str, int] = {}
    by_rule: dict[str, int] = {}

    for p in pages:
        by_type[p["type"]] += 1
        by_section[p["section"]] += 1
        by_confidence[p["confidence"]] = by_confidence.get(p["confidence"], 0) + 1
        by_rule[str(p["rule"])] = by_rule.get(str(p["rule"]), 0) + 1

    relasi = relasi_numbers or set()
    lintas = lintas_numbers or set()

    return {
        "by_type": by_type,
        "by_section": by_section,
        "by_confidence": by_confidence,
        "by_rule": by_rule,
        "image_only_pages": [p["page"] for p in pages if p["word_count"] == 0],
        "unknown_pages": [p["page"] for p in pages if p["type"] == "unknown"],
        "multi_table_pages": [p["page"] for p in pages if p["table_header_count"] >= 2],
        "train_numbers": {
            "relasi_distinct": len(relasi),
            "lintas_distinct": len(lintas),
            "union_distinct": len(relasi | lintas),
        },
    }


def write_json(inventory: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify every page of the Gapeka PDF.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--no-report", action="store_true", help="skip report generation")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"error: PDF not found at {args.pdf}", file=sys.stderr)
        return 2

    inventory = build_inventory(args.pdf)
    write_json(inventory, args.out)

    if not args.no_report:
        from pipeline.report import render_report

        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(inventory), encoding="utf-8")

    summary = inventory["summary"]
    print(f"pages: {inventory['source']['page_count']}")
    print(f"by type: {summary['by_type']}")
    print(f"unknown: {len(summary['unknown_pages'])}")
    print(f"wrote {args.out}")
    if not args.no_report:
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
