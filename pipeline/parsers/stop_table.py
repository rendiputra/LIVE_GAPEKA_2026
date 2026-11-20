"""Phase 1c: pilot parser for per-train stop tables (intercity book).

Row and column reconstruction is delegated to ``table_geometry`` (Hard Rule 11).
This module turns geometry into stop records and applies the document's cell
conventions, recording ``needs_review`` at exactly the places where a value is
missing without an explicit "empty" marker.

Conventions applied (each one is reported if a counter-example appears):

- ``Ls`` in the *Datang* column means the train passes through without stopping.
  Keep the raw text and set ``stop_type = "pass"``.
- ``-`` is the document's explicit empty-cell marker -> ``null``, no review.
- A cell that is blank when the document's convention says it should hold a value
  -> ``null`` + ``needs_review``.
- Footnote text (``= ka 46 (ka 46 //)``) is captured verbatim; its meaning is
  NOT interpreted in Phase 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.parsers.table_geometry import (
    COL_ARRIVE,
    COL_DEPART,
    COL_NO,
    COL_NOTE,
    COL_SPEED,
    COL_STATION,
    TableBlock,
    Word,
)

EMPTY_MARKER = "-"
PASS_MARKER = "LS"

TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
TRAIN_TITLE_RE = re.compile(
    r"KA\s+(\d+[A-Z]?)\s*\((.*?)\)\s*(?:RELASI|LINTAS PELAYANAN)\s*([A-Z0-9]+)\s*-\s*([A-Z0-9]+)"
)
STATION_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2,5})\)$")


@dataclass
class Cell:
    """One parsed cell with its provenance."""

    value: str | None
    raw: str
    page: int
    bbox: list[float] | None

    def as_dict(self) -> dict:
        return {"value": self.value, "raw": self.raw, "page": self.page, "bbox": self.bbox}


@dataclass
class Stop:
    seq: int | None
    station_name: str | None
    station_code: str | None
    speed: Cell
    arrive: Cell
    depart: Cell
    note: Cell
    stop_type: str
    needs_review: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "station_name": self.station_name,
            "station_code": self.station_code,
            "speed": self.speed.as_dict(),
            "arrive": self.arrive.as_dict(),
            "depart": self.depart.as_dict(),
            "note": self.note.as_dict(),
            "stop_type": self.stop_type,
            "needs_review": self.needs_review,
            "provenance": self.provenance,
        }


@dataclass
class ParsedTrain:
    train_no: str | None
    name: str | None
    origin: str | None
    destination: str | None
    page: int
    header_y: float
    stops: list[Stop] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    column_source: str = "ruling"

    def as_dict(self) -> dict:
        return {
            "train_no": self.train_no,
            "name": self.name,
            "origin": self.origin,
            "destination": self.destination,
            "page": self.page,
            "header_y": round(self.header_y, 2),
            "column_source": self.column_source,
            "stops": [s.as_dict() for s in self.stops],
            "notes": self.notes,
            "needs_review": self.needs_review,
        }


def _join(words: list[Word]) -> str:
    return " ".join(w.text for w in words).strip()


def _bbox(words: list[Word]) -> list[float] | None:
    if not words:
        return None
    return [
        round(min(w.x0 for w in words), 2),
        round(min(w.y0 for w in words), 2),
        round(max(w.x1 for w in words), 2),
        round(max(w.y1 for w in words), 2),
    ]


def _cell(block: TableBlock, row: list[Word], key: str) -> Cell:
    words = block.cell(row, key)
    return Cell(value=_join(words) or None, raw=_join(words), page=block.page, bbox=_bbox(words))


def parse_title(block: TableBlock) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract train_no / name / origin / destination from the table title."""
    text = " ".join(w.text for w in block.title_words)
    match = TRAIN_TITLE_RE.search(" ".join(text.upper().split()))
    if not match:
        return None, None, None, None
    return match.group(1), match.group(2).title(), match.group(3), match.group(4)


def parse_stop(block: TableBlock, row: list[Word], previous_seq: int | None) -> Stop | None:
    """Convert one geometry row into a Stop, or None if it is not a stop row."""
    seq_cell = _cell(block, row, COL_NO)
    station_cell = _cell(block, row, COL_STATION)

    if seq_cell.value is None or station_cell.value is None:
        return None
    if not seq_cell.value.isdigit():
        return None

    seq = int(seq_cell.value)
    if previous_seq is not None and seq != previous_seq + 1:
        # A gap means the row grouping or the PDF itself skipped something.
        pass

    station_match = STATION_RE.match(station_cell.raw)
    if station_match:
        name, code = station_match.group(1).strip(), station_match.group(2)
    else:
        name, code = station_cell.raw, None

    speed = _cell(block, row, COL_SPEED)
    arrive = _cell(block, row, COL_ARRIVE)
    depart = _cell(block, row, COL_DEPART)
    note = _cell(block, row, COL_NOTE)

    review: list[str] = []

    if code is None:
        review.append("station_code_unparsed")

    # stop_type from the Datang column, where the document places Ls.
    arrive_raw = (arrive.raw or "").strip()
    if arrive_raw.upper() == PASS_MARKER:
        stop_type = "pass"
        arrive_value = None
    elif arrive_raw == EMPTY_MARKER:
        stop_type = "stop"
        arrive_value = None
    elif TIME_RE.match(arrive_raw):
        stop_type = "stop"
        arrive_value = arrive_raw
    elif arrive_raw == "":
        stop_type = "stop"
        arrive_value = None
        review.append("arrive_blank")
    else:
        stop_type = "stop"
        arrive_value = None
        review.append(f"arrive_unrecognised:{arrive_raw}")

    depart_raw = (depart.raw or "").strip()
    if depart_raw == EMPTY_MARKER or depart_raw == "":
        depart_value = None
        if depart_raw == "" and stop_type != "pass":
            review.append("depart_blank")
    elif TIME_RE.match(depart_raw):
        depart_value = depart_raw
    else:
        depart_value = None
        review.append(f"depart_unrecognised:{depart_raw}")

    # A pass row shows Ls in Datang and a time in Berangkat (the pass time).
    if stop_type == "pass" and depart_value is None and arrive_raw.upper() != PASS_MARKER:
        review.append("pass_without_time")

    speed_raw = (speed.raw or "").strip()
    if speed_raw == EMPTY_MARKER:
        speed_value = None
    elif speed_raw.isdigit():
        speed_value = speed_raw
    elif speed_raw == "":
        speed_value = None
        review.append("speed_blank")
    else:
        speed_value = None
        review.append(f"speed_unrecognised:{speed_raw}")

    return Stop(
        seq=seq,
        station_name=name,
        station_code=code,
        speed=Cell(speed_value, speed.raw, speed.page, speed.bbox),
        arrive=Cell(arrive_value, arrive.raw, arrive.page, arrive.bbox),
        depart=Cell(depart_value, depart.raw, depart.page, depart.bbox),
        note=note,
        stop_type=stop_type,
        needs_review=review,
        provenance={
            "page": block.page,
            "seq_bbox": seq_cell.bbox,
            "station_bbox": station_cell.bbox,
            "row_y": round(row[0].y_centre, 2),
        },
    )


def parse_block(block: TableBlock) -> ParsedTrain | None:
    """Parse one table block into a ParsedTrain."""
    train_no, name, origin, destination = parse_title(block)
    train = ParsedTrain(
        train_no=train_no,
        name=name,
        origin=origin,
        destination=destination,
        page=block.page,
        header_y=block.header_y,
        column_source=block.column_source,
    )
    if train_no is None:
        train.needs_review.append("train_header_unparsed")

    previous_seq: int | None = None
    for row in block.rows:
        stop = parse_stop(block, row, previous_seq)
        if stop is None:
            # Any leftover row text that is not a stop is captured as a note.
            text = " ".join(w.text for w in row).strip()
            if text:
                train.notes.append(text)
            continue
        if previous_seq is not None and stop.seq != previous_seq + 1:
            train.needs_review.append(
                f"seq_gap:{previous_seq}->{stop.seq}@{stop.station_code or '?'}"
            )
        previous_seq = stop.seq
        train.stops.append(stop)

    if not train.stops:
        train.needs_review.append("no_stops_parsed")

    seqs = [s.seq for s in train.stops]
    if seqs and seqs[0] != 1:
        train.needs_review.append(f"does_not_start_at_seq_1:starts_{seqs[0]}")

    return train


def parse_page(
    block_list: list[TableBlock],
) -> list[ParsedTrain]:
    return [t for t in (parse_block(b) for b in block_list) if t is not None]


def merge_continuations(trains: list[ParsedTrain]) -> list[ParsedTrain]:
    """Attach a title-less block to the train it continues.

    A table block with no ``KA nnn (...)`` title and a first sequence number that
    follows the previous train's last number is a continuation of that train on
    the next page. Anything else stays a separate, flagged train.
    """
    merged: list[ParsedTrain] = []
    for train in trains:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and train.train_no is None
            and train.stops
            and previous.stops
            and train.stops[0].seq is not None
            and previous.stops[-1].seq is not None
            and train.stops[0].seq == previous.stops[-1].seq + 1
        ):
            previous.stops.extend(train.stops)
            previous.notes.extend(train.notes)
            previous.needs_review = [
                r for r in previous.needs_review if not r.startswith("does_not_start_at_seq_1")
            ]
            previous.needs_review.append(
                f"continued_on_page_{train.page}_from_seq_{train.stops[0].seq - 1}"
            )
            continue
        merged.append(train)
    return merged


def footnote_patterns(trains: list[ParsedTrain]) -> list[dict]:
    """Collect distinct footnote patterns verbatim (never interpreted)."""
    seen: dict[str, int] = {}
    for train in trains:
        for stop in train.stops:
            raw = (stop.note.raw or "").strip()
            if raw:
                seen[raw] = seen.get(raw, 0) + 1
        for note in train.notes:
            stripped = note.strip()
            if stripped:
                seen[stripped] = seen.get(stripped, 0) + 1
    return [
        {"text": text, "count": count} for text, count in sorted(seen.items(), key=lambda kv: kv[0])
    ]
