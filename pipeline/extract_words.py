"""Phase 1a: extract words + bboxes from every page into the raw layer.

The raw layer is **append-only** (Hard Rule 2):

- an existing ``page_XXXX.json`` is never rewritten, even if the extractor changes;
- a ``manifest.json`` records the SHA-256 of every file actually on disk;
- re-running the same extractor on the same PDF produces identical files.

Use ``--verify`` to re-extract pages and compare hashes *without* writing, which
is how extractor drift is detected after a PyMuPDF upgrade.

Usage:
    python -m pipeline.extract_words --pdf data/input/GAPEKA_2026.pdf
    python -m pipeline.extract_words --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pymupdf

from pipeline.inventory import sha256_of

DEFAULT_PDF = Path("data/input/GAPEKA_2026.pdf")
DEFAULT_OUT = Path("data/raw/words")

SCHEMA_VERSION = 1

# Compact, fixed-order word record. The keys are documented in the manifest so a
# reader never has to guess:
#   [x0, y0, x1, y1, text, block_no, line_no, word_no]
WORD_FIELDS = ["x0", "y0", "x1", "y1", "text", "block", "line", "word"]


def page_payload(doc: pymupdf.Document, index: int) -> dict:
    """Build the raw payload for one page. Pure function of the PDF."""
    page = doc[index]
    words = [
        [
            round(w[0], 3),
            round(w[1], 3),
            round(w[2], 3),
            round(w[3], 3),
            w[4],
            w[5],
            w[6],
            w[7],
        ]
        for w in page.get_text("words")
    ]
    return {
        "page": index + 1,
        "rotation": page.rotation,
        "width_pt": round(page.rect.width, 3),
        "height_pt": round(page.rect.height, 3),
        "mediabox": [round(v, 3) for v in page.mediabox],
        "word_count": len(words),
        "word_fields": WORD_FIELDS,
        "words": words,
    }


def dump(payload: dict) -> str:
    """Serialise deterministically: no keys order drift, no float repr drift."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def page_path(out_dir: Path, page_no: int) -> Path:
    return out_dir / f"page_{page_no:04d}.json"


def manifest_path(out_dir: Path) -> Path:
    return out_dir / "manifest.json"


def load_manifest(out_dir: Path) -> dict | None:
    path = manifest_path(out_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(pdf_path: Path, out_dir: Path, entries: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "path": str(pdf_path),
            "sha256": sha256_of(pdf_path),
            "page_count": len(entries),
        },
        "tool": {
            "pymupdf": pymupdf.version[1],
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "word_fields": WORD_FIELDS,
        "pages": entries,
    }


def write_manifest(pdf_path: Path, out_dir: Path, entries: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(out_dir).write_text(
        json.dumps(build_manifest(pdf_path, out_dir, entries), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(pdf_path: Path, out_dir: Path, limit: int | None = None) -> int:
    doc = pymupdf.open(pdf_path)
    try:
        total = doc.page_count if limit is None else min(limit, doc.page_count)
        out_dir.mkdir(parents=True, exist_ok=True)

        entries: list[dict] = []
        written = skipped = 0

        for index in range(total):
            page_no = index + 1
            path = page_path(out_dir, page_no)
            payload = page_payload(doc, index)

            if path.exists():
                # Append-only: never rewrite. Trust the file on disk and record
                # its hash, so the manifest always describes reality.
                skipped += 1
                entries.append(
                    {
                        "page": page_no,
                        "file": path.name,
                        "sha256": file_sha256(path),
                        "word_count": json.loads(path.read_text(encoding="utf-8"))["word_count"],
                        "action": "kept",
                    }
                )
                continue

            path.write_text(dump(payload), encoding="utf-8")
            written += 1
            entries.append(
                {
                    "page": page_no,
                    "file": path.name,
                    "sha256": file_sha256(path),
                    "word_count": payload["word_count"],
                    "action": "written",
                }
            )

        write_manifest(pdf_path, out_dir, entries)

        empty = [e["page"] for e in entries if e["word_count"] == 0]
        print(f"pages: {total}")
        print(f"written: {written}  kept (already present): {skipped}")
        print(f"pages with zero words: {len(empty)} {empty if empty else ''}")
        print(f"wrote {out_dir}")
        return 0
    finally:
        doc.close()


def verify(pdf_path: Path, out_dir: Path, limit: int | None = None) -> int:
    """Re-extract and compare hashes. Writes nothing."""
    doc = pymupdf.open(pdf_path)
    try:
        total = doc.page_count if limit is None else min(limit, doc.page_count)
        mismatches: list[int] = []
        missing: list[int] = []

        for index in range(total):
            page_no = index + 1
            path = page_path(out_dir, page_no)
            if not path.exists():
                missing.append(page_no)
                continue
            expected = hashlib.sha256(dump(page_payload(doc, index)).encode("utf-8")).hexdigest()
            if expected != file_sha256(path):
                mismatches.append(page_no)

        print(f"pages checked: {total}")
        print(f"missing files: {len(missing)} {missing[:20]}")
        print(f"hash mismatches: {len(mismatches)} {mismatches[:20]}")
        return 0 if not mismatches and not missing else 1
    finally:
        doc.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract words + bboxes for every page.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=None, help="only the first N pages")
    parser.add_argument("--verify", action="store_true", help="re-extract and compare hashes")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"error: PDF not found at {args.pdf}", file=sys.stderr)
        return 2

    if args.verify:
        return verify(args.pdf, args.out, args.limit)
    return run(args.pdf, args.out, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
