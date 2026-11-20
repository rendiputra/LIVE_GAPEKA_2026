"""Lampiran IV summary tables: per-train REGULER / FAKULTATIF classification.

Report-only. The goal is to test, with data, whether the ``F`` suffix in a train
number co-occurs with a ``FAKULTATIF`` classification in the summary tables. No
meaning is assumed from the number format; evidence only.

Columns (observed): ``seq | train_no | JENIS | name | identity | n | lintas |
badan | jarak | km | berangkat | datang | jam``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.parsers.table_geometry import Word, words_from_raw

SUMMARY_PAGES = tuple(range(1829, 1865))
CATEGORIES = ("REGULER", "FAKULTATIF")

TIME_RE = re.compile(r"^\d{1,2}[:.]\d{2}$")
SEQ_RE = re.compile(r"^\d{1,3}$")
# Train numbers may carry a leading letter (locomotive dinas numbers such as
# "L2521-2") as well as a trailing suffix ("141F").
TRAIN_NO_RE = re.compile(r"^[A-Z]?\d{1,4}[A-Z]?(?:-[A-Z]?\d{1,4}[A-Z]?)*$")


@dataclass
class SummaryEntry:
    page: int
    seq: str | None
    train_no: str | None
    category: str | None
    name: str | None
    relation: str | None
    depart: str | None
    arrive: str | None
    needs_review: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "seq": self.seq,
            "train_no": self.train_no,
            "category": self.category,
            "name": self.name,
            "relation": self.relation,
            "depart": self.depart,
            "arrive": self.arrive,
            "needs_review": self.needs_review,
            "provenance": self.provenance,
        }


def rows(words: list[Word]) -> list[list[Word]]:
    """Group summary words into rows keyed on the table's own line structure.

    A summary row is one printed line (a wrapped name may add continuation lines
    without a sequence number). Lines are delimited by the sequence-number column,
    whose x-position is derived per page from the most common left-edge x of
    short integer tokens — not from a hardcoded value and not from the page's
    leftmost word, which may be a classification block.
    """
    body = [w for w in words if w.y0 > 70]
    if not body:
        return []

    # The sequence column is the LEFTMOST x that recurs across many lines. Other
    # numeric columns (JARAK, KM) are also dense but sit further right.
    counts: Counter[float] = Counter()
    for word in body:
        if SEQ_RE.match(word.text.strip()):
            counts[round(word.x0, 1)] += 1
    if not counts:
        return []
    threshold = max(3, max(counts.values()) // 3)
    dense = [x for x, n in counts.items() if n >= threshold]
    seq_x = min(dense) if dense else min(counts, key=lambda x: x)
    seq_band = (seq_x - 4, seq_x + 30)

    anchors = sorted(
        [w for w in body if seq_band[0] <= w.x0 < seq_band[1] and SEQ_RE.match(w.text.strip())],
        key=lambda w: w.y0,
    )
    if not anchors:
        return []

    # Train-number column sits just right of the sequence column.
    number_band = (seq_x + 25, seq_x + 125)

    def same_line(word: Word) -> list[Word]:
        return [w for w in body if abs(w.y0 - word.y0) <= 3.0]

    rows_out: list[list[Word]] = []
    for index, anchor in enumerate(anchors):
        line = same_line(anchor)
        has_category = any(w.text.strip().upper() in CATEGORIES for w in line)
        has_number = any(
            number_band[0] <= w.x0 < number_band[1] and TRAIN_NO_RE.match(w.text.strip())
            for w in line
        )
        if not (has_category and has_number):
            continue
        # Bands are delimited by midpoints between consecutive anchors, so every
        # neighbouring line is fully contained (a line's words differ in y0 by up
        # to ~1pt, and an anchor-only band would cut them off).
        top = (anchors[index - 1].y0 + anchor.y0) / 2 if index > 0 else anchor.y0 - 4
        bottom = (
            (anchor.y0 + anchors[index + 1].y0) / 2
            if index + 1 < len(anchors)
            else max(w.y1 for w in body) + 1
        )
        # A page can stack two tables, and the second table's header block sits
        # between two data rows. Header furniture is dropped per row so it can
        # never displace the train number or category.
        block_keywords = {
            "KLASIFIKASI",
            "WILAYAH",
            "GAPEKA",
            "JUMLAH",
            "KILOMETER",
            "URUT",
            "NOMOR",
            "JENIS",
            "NAMA",
            "LINTAS",
            "PELAYANAN",
            "BADAN",
            "PENYELENGGARA",
            "SARANA",
            "JARAK",
            "JAM",
            "WAKTU",
            "PERJALANAN",
            "BERANGKAT",
            "DATANG",
            "KERETA",
            "API",
            "KA",
        }
        rows_out.append(
            sorted(
                (
                    w
                    for w in body
                    if top <= w.y0 < bottom and w.text.strip().upper() not in block_keywords
                ),
                key=lambda w: (w.y0, w.x0),
            )
        )
    return rows_out


def parse_row(row: list[Word], page: int) -> SummaryEntry | None:
    """Parse one summary row. Columns are located by x-band, not token index."""
    if not row:
        return None
    texts = [w.text.strip() for w in row]

    # Sequence = the leftmost token that actually looks like a sequence number.
    # row[0] may be leftover header furniture such as "GAPEKA" or "2026".
    seq_candidates = [w for w in row if SEQ_RE.match(w.text.strip()) and w.x0 < 90]
    seq_word = min(seq_candidates, key=lambda w: w.x0) if seq_candidates else row[0]
    seq_x = seq_word.x0
    number_band = (seq_x + 25, seq_x + 125)

    train_no = next(
        (
            w.text.strip()
            for w in row
            if number_band[0] <= w.x0 < number_band[1] and TRAIN_NO_RE.match(w.text.strip())
        ),
        None,
    )

    # The category is the token immediately right of the train number, on the
    # same printed line.
    category = None
    if train_no is not None:
        number_word = next(w for w in row if w.text.strip() == train_no)
        for word in sorted((w for w in row if w.x0 > number_word.x1), key=lambda w: w.x0):
            if word.text.strip().upper() in CATEGORIES:
                category = word.text.strip().upper()
                break

    relation = next((t for t in texts if re.match(r"^[A-Z]{2,5}(?:-[A-Z]{2,5})+$", t)), None)

    # A row whose "name" is a column header word ("NAMA", "JENIS") comes from the
    # header band or a page's classification block, not from a train row.
    header_words = {"NAMA", "JENIS", "KA", "KERETA", "API", "LINTAS", "PELAYANAN"}
    if any(t.upper() in header_words for t in texts):
        return None
    # "GAPEKA 2026" in a page header also yields a stray 4-digit token.
    if train_no == "2026":
        return None
    times = [t for t in texts if TIME_RE.match(t)]

    review: list[str] = []
    if train_no is None:
        review.append("missing_train_no")
    if category is None:
        review.append("missing_category")
    if category is None and relation is None:
        return None

    # The name is the first plain word after the category column.
    name = None
    if category is not None:
        category_word = next((w for w in row if w.text.strip().upper() == category), None)
        if category_word is not None:
            for word in sorted((w for w in row if w.x0 > category_word.x1), key=lambda w: w.x0):
                token = word.text.strip()
                if (
                    token
                    and token.upper() not in CATEGORIES
                    and not TIME_RE.match(token)
                    and not re.match(r"^[A-Z]{2,5}(?:-[A-Z]{2,5})+$", token)
                    and not token.replace(",", "").replace(".", "").isdigit()
                ):
                    name = token
                    break

    return SummaryEntry(
        page=page,
        seq=seq_word.text.strip() if SEQ_RE.match(seq_word.text.strip()) else None,
        train_no=train_no,
        category=category,
        name=name,
        relation=relation,
        depart=times[0] if times else None,
        arrive=times[1] if len(times) > 1 else None,
        needs_review=review,
        provenance={
            "page": page,
            "bbox": [
                round(min(w.x0 for w in row), 2),
                round(min(w.y0 for w in row), 2),
                round(max(w.x1 for w in row), 2),
                round(max(w.y1 for w in row), 2),
            ],
        },
    )


def parse_summary(words_dir: Path) -> list[SummaryEntry]:
    entries: list[SummaryEntry] = []
    for page in SUMMARY_PAGES:
        path = words_dir / f"page_{page:04d}.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in rows(words_from_raw(payload)):
            entry = parse_row(row, page)
            if entry is not None and entry.train_no is not None:
                entries.append(entry)
    return entries


PLAIN_TRAIN_NO_RE = re.compile(r"^\d{1,4}[A-Z]?$")


def split_train_numbers(text: str | None) -> list[str]:
    """Split a multi-train row ("240-241-242") but not a locomotive series.

    Locomotive dinas numbers look like ``L2724F-1`` or ``R252-1``: one number
    with a trailing index. Splitting those would invent train numbers such as
    ``1``, so a split only happens when every part is a plain train number.
    """
    if not text:
        return []
    parts = text.split("-")
    if len(parts) > 1 and all(PLAIN_TRAIN_NO_RE.match(part) for part in parts):
        return parts
    return [text]


def f_suffix_analysis(entries: list[SummaryEntry]) -> dict:
    """Test whether the F suffix co-occurs with FAKULTATIF. Evidence only."""
    by_number: dict[str, list[SummaryEntry]] = {}
    for entry in entries:
        for number in split_train_numbers(entry.train_no):
            by_number.setdefault(number, []).append(entry)

    has_f: list[dict] = []
    no_f: list[dict] = []
    for number, items in sorted(by_number.items()):
        categories = sorted({i.category for i in items if i.category})
        record = {
            "train_no": number,
            "categories": categories,
            "pages": sorted({i.page for i in items}),
            "names": sorted({i.name for i in items if i.name}),
        }
        # A number "has a suffix" when it carries a letter that is not the leading
        # dinas marker: "141F", "259F", "L2501F-2".
        if re.search(r"F", number, re.IGNORECASE):
            has_f.append(record)
        else:
            no_f.append(record)

    f_but_reguler = [r for r in has_f if r["categories"] and "FAKULTATIF" not in r["categories"]]
    f_with_fakultatif = [r for r in has_f if "FAKULTATIF" in r["categories"]]
    f_with_no_category = [r for r in has_f if not r["categories"]]
    fakultatif_no_suffix = [r for r in no_f if "FAKULTATIF" in r["categories"]]

    return {
        "note": (
            "Evidence only. No meaning is assumed from the number format. "
            "Categories come from the Lampiran IV summary tables."
        ),
        "summary_entries": len(entries),
        "distinct_train_numbers": len(by_number),
        "category_counts": dict(Counter(i.category for i in entries)),
        "numbers_with_f_suffix": len(has_f),
        "numbers_without_suffix": len(no_f),
        "suffix_and_fakultatif": len(f_with_fakultatif),
        "suffix_but_not_fakultatif": f_but_reguler,
        "suffix_without_any_category": f_with_no_category,
        "fakultatif_without_suffix": fakultatif_no_suffix,
        "suffix_examples": has_f[:20],
    }
