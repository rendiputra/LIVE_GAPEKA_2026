"""Phase 1b: parse the intercity index pages into an expected-train list.

The index is the **primary authority** for which trains exist and their printed
page numbers (AGENTS.md section 1.2). Columns are derived from x-coordinates, not
from the text stream (Hard Rule 11).

Ambiguity policy: anything that cannot be read with certainty becomes ``null``
plus a ``needs_review`` reason. It is never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.parsers.table_geometry import Word, label

# Index columns, left to right. Two shapes exist:
#   Lampiran-II index : seq | train_no | class | name | relation | depart | arrive | page
#   simple index      : seq | train_no | class | name | relation | depart | arrive | page
# The x-positions differ per book, so the layout is inferred from the header row
# when present and from value shapes otherwise.
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
TRAIN_NO_RE = re.compile(r"^\d{1,4}[A-Z]?(?:-\d{1,4}[A-Z]?)*$")
RELATION_RE = re.compile(r"^[A-Z]{2,5}(\s*-\s*[A-Z]{2,5})+$")
SEQ_RE = re.compile(r"^\d{1,3}$")


@dataclass
class IndexEntry:
    seq: str | None
    train_no: str | None
    train_class: str | None
    name: str | None
    relation: str | None
    depart: str | None
    arrive: str | None
    printed_page: str | None
    needs_review: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "train_no": self.train_no,
            "class": self.train_class,
            "name": self.name,
            "relation": self.relation,
            "depart": self.depart,
            "arrive": self.arrive,
            "printed_page": self.printed_page,
            "needs_review": self.needs_review,
            "provenance": self.provenance,
        }


def _rows(words: list[Word], tolerance: float = 3.0) -> list[list[Word]]:
    """Group index words into rows, anchored on the sequence-number column.

    Index rows wrap: the train name can occupy two lines and the relation three,
    and each wrapped line is emitted as a separate text block. Block numbers are
    therefore unreliable as a row key. Instead, every sequence number starts a row
    and absorbs all words down to the next sequence number.
    """
    body = [w for w in words if label(w.text) not in ("URUT", "KA", "BRK", "DAT", "DAFTAR", "ISI")]
    if not body:
        return []

    left_edge = min(w.x0 for w in body)
    seq_tokens = [w for w in body if w.x0 <= left_edge + 40 and SEQ_RE.match(w.text.strip())]
    if not seq_tokens:
        return []

    anchors = sorted(seq_tokens, key=lambda w: (w.y0, w.x0))
    rows: list[list[Word]] = []
    for index, anchor in enumerate(anchors):
        top = anchor.y0 - 2
        bottom = (
            anchors[index + 1].y0 - 2
            if index + 1 < len(anchors)
            else max((w.y1 for w in body), default=anchor.y1) + 1
        )
        row = [w for w in body if top <= w.y0 < bottom]
        rows.append(sorted(row, key=lambda w: (w.y0, w.x0)))
    return rows


# Column x-bands, derived from the index pages themselves (all index pages share
# the same left-to-right layout). Boundaries are taken from the observed gaps
# between columns, expressed relative to the sequence column's left edge.
#
#   seq | train_no | class | name | relation | depart | arrive | printed_page
#
# "class" and "name" are read as one band and split by the class vocabulary,
# because multi-line names wrap and cannot be separated by x alone.
CLASS_WORDS = {
    "ARGO",
    "EKSEKUTIF",
    "EKONOMI",
    "BISNIS",
    "CAMPURAN",
    "JARAK",
    "JAUH",
    "LOKAL",
    "COMMUTER",
    "LINE",
    "PARAHYANGAN",
    "FEEDER",
    "BARANG",
    "PARCEL",
    "TANKER",
    "BHP",
}


def _bands(row: list[Word]) -> dict[str, list[Word]]:
    """Split a row into semantic bands using x-position, not keyword order."""
    if not row:
        return {}
    seq_word = row[0]
    # Relative offsets calibrated on the index pages; the seq token's left edge
    # is the anchor so the bands stay correct if the page margin shifts.
    base = seq_word.x0
    limits = {
        "seq": (base - 5, base + 25),
        "train_no": (base + 30, base + 65),
        "classname": (base + 68, base + 285),
        "relation": (base + 285, base + 335),
        "depart": (base + 335, base + 370),
        "arrive": (base + 370, base + 410),
        "printed_page": (base + 410, base + 500),
    }
    bands: dict[str, list[Word]] = {}
    for word in row:
        for name, (x0, x1) in limits.items():
            if x0 <= word.x0 < x1:
                bands.setdefault(name, []).append(word)
                break
    return bands


def parse_index_row(row: list[Word], page: int) -> IndexEntry | None:
    """Turn one index row's words into an IndexEntry.

    Columns are located by x-band, so a row whose printed page happens to be
    numeric can never be mistaken for an arrival time.
    """
    bands = _bands(row)
    if "seq" not in bands or "train_no" not in bands:
        return None

    seq = bands["seq"][0].text
    train_no = bands["train_no"][0].text
    if not SEQ_RE.match(seq) or not TRAIN_NO_RE.match(train_no):
        return None

    classname = [w.text for w in bands.get("classname", [])]
    train_class = None
    name = None
    if classname:
        split = 0
        while split < len(classname) and classname[split].upper() in CLASS_WORDS:
            split += 1
        train_class = " ".join(classname[:split]) or None
        name = " ".join(classname[split:]) or None

    def first_text(band: str, pattern: re.Pattern[str]) -> str | None:
        for word in bands.get(band, []):
            if pattern.match(word.text):
                return word.text
        return None

    relation = None
    relation_words = bands.get("relation", [])
    if relation_words:
        relation = "".join(w.text for w in relation_words).strip()

    depart = first_text("depart", TIME_RE)
    arrive = first_text("arrive", TIME_RE)
    printed = first_text("printed_page", re.compile(r"^\d{1,4}$"))

    review: list[str] = []
    if relation is None:
        review.append("missing_relation")
    if depart is None:
        review.append("missing_depart")
    if arrive is None:
        review.append("missing_arrive")
    if printed is None:
        review.append("missing_printed_page")

    return IndexEntry(
        seq=seq,
        train_no=train_no,
        train_class=train_class,
        name=name,
        relation=relation,
        depart=depart,
        arrive=arrive,
        printed_page=printed,
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


def parse_index_pages(pages: dict[int, list[Word]]) -> list[IndexEntry]:
    """Parse a set of index pages into entries, in page order."""
    entries: list[IndexEntry] = []
    for page in sorted(pages):
        for row in _rows(pages[page]):
            entry = parse_index_row(row, page)
            if entry is not None:
                entries.append(entry)
    return entries
