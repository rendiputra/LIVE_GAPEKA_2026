"""Phase 1c/2: per-train stop-table parser (intercity book).

Row and column reconstruction is delegated to ``table_geometry`` (Hard Rule 11).
This module turns geometry into stop records and applies the document's cell
conventions.

Conventions (AGENTS.md section 5, observed in sampling):

- ``Ls`` in the *Datang* column means the train passes through without stopping.
  The raw text is kept and ``stop_type = "pass"``.
- ``-`` is the document's explicit empty-cell marker. It is unflagged **only** at
  the three structurally expected positions: **Datang** at the first sequence,
  **Berangkat** at the last sequence, and **Kecepatan** at the last sequence.
  A ``-`` anywhere else becomes ``null`` + ``needs_review``.
- A blank cell where the convention expects a value becomes ``null`` +
  ``needs_review``.
- ``raw`` is preserved for **every** cell. ``0`` and ``-`` are never normalised
  into the same thing: some trains print speed ``0`` at a terminal, others ``-``.
- Footnote text (``= ka 46 (ka 46 //)``) is captured verbatim; its meaning is not
  interpreted here.

Flags come in two kinds and are never mixed:

- ``info`` — a structural observation that is not in doubt, e.g. a table that
  continues on the next page. These do not block anything.
- ``needs_review`` — a real doubt that a human must resolve.
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

# A midnight rollover is normal; a jump larger than this is not.
MAX_PLAUSIBLE_GAP_SECONDS = 12 * 3600

COMPLETENESS_COMPLETE = "complete"
COMPLETENESS_TRUNCATED = "truncated_at_loaded_pages"
COMPLETENESS_UNKNOWN = "unknown"


def seconds_of(value: str | None) -> int | None:
    if not value or not TIME_RE.match(value):
        return None
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


@dataclass
class Cell:
    """One parsed cell. ``raw`` is always the text exactly as printed.

    ``source`` says where the value came from:

    - ``printed``   — a clock time printed in the cell;
    - ``not_printed`` — the document deliberately prints no time here (``-``);
    - ``empty``     — the cell is blank;
    - ``derived``   — reserved for engine-side estimates. The parser NEVER sets
      this: estimated times must not enter the parsed layer (ADR 002 / Q1).
    ``estimated`` mirrors ``source == "derived"`` for consumers that only care
    whether the value is observed or inferred.
    """

    value: str | None
    raw: str
    page: int
    bbox: list[float] | None
    source: str = "printed"

    @property
    def estimated(self) -> bool:
        return self.source == "derived"

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "raw": self.raw,
            "page": self.page,
            "bbox": self.bbox,
            "source": self.source,
            "estimated": self.estimated,
        }


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
    day_offset: int = 0
    info: list[str] = field(default_factory=list)
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
            "day_offset": self.day_offset,
            "info": self.info,
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
    info: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    column_source: str = "ruling"
    completeness: str = COMPLETENESS_UNKNOWN
    loaded_pages: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "train_no": self.train_no,
            "name": self.name,
            "origin": self.origin,
            "destination": self.destination,
            "page": self.page,
            "header_y": round(self.header_y, 2),
            "column_source": self.column_source,
            "completeness": self.completeness,
            "loaded_pages": self.loaded_pages,
            "stops": [s.as_dict() for s in self.stops],
            "notes": self.notes,
            "info": self.info,
            "needs_review": self.needs_review,
        }


def _join(words: list[Word]) -> str:
    """Join cell words in reading order.

    A multi-line cell (a station name wrapped over two or three lines) must be
    read top-down, then left-to-right — not purely left-to-right, which would
    interleave the lines ("Yogyakarta Airport International" vs
    "Yogyakarta International Airport").
    """
    if not words:
        return ""
    ordered = sorted(words, key=lambda w: (round(w.y0), w.x0))
    return " ".join(w.text for w in ordered).strip()


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
    text = " ".join(w.text for w in block.title_words)
    match = TRAIN_TITLE_RE.search(" ".join(text.upper().split()))
    if not match:
        return None, None, None, None
    return match.group(1), match.group(2).title(), match.group(3), match.group(4)


def _classify_time_cell(raw: str, kind: str) -> tuple[str | None, list[str], list[str], str]:
    """Classify a time-column cell. Returns (value, info, needs_review, source)."""
    text = raw.strip()
    if text == "":
        return None, [], [f"{kind}_blank"], "empty"
    if text == EMPTY_MARKER:
        # Positional expectations are applied later, once the last seq is known.
        # "-" means the document states no time here, which is different from a
        # blank cell.
        return None, [], [], "not_printed"
    if TIME_RE.match(text):
        return text, [], [], "printed"
    return None, [], [f"{kind}_unrecognised:{text}"], "empty"


def parse_stop(block: TableBlock, row: list[Word]) -> Stop | None:
    """Convert one geometry row into a Stop, or None if it is not a stop row."""
    seq_cell = _cell(block, row, COL_NO)
    station_cell = _cell(block, row, COL_STATION)

    if seq_cell.value is None or station_cell.value is None:
        return None
    if not seq_cell.value.isdigit():
        return None

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

    arrive_raw = (arrive.raw or "").strip()
    depart_raw = (depart.raw or "").strip()

    if arrive_raw.upper() == PASS_MARKER:
        # "Ls" states that the train passes through; it is not a clock reading.
        stop_type = "pass"
        arrive_value = None
        arrive_source = "not_printed"
    else:
        stop_type = "stop"
        arrive_value, _ai, arrive_flags, arrive_source = _classify_time_cell(arrive_raw, "arrive")
        review.extend(arrive_flags)

    depart_value, _di, depart_flags, depart_source = _classify_time_cell(depart_raw, "depart")
    review.extend(depart_flags)

    # A pass row usually carries its passing time in Berangkat. The document also
    # prints "Ls" together with "-" in Berangkat (observed across Book 1, e.g.
    # KA 1 seq 87-96). That combination is a printed value, not a gap, so it is
    # recorded as info rather than as a doubt.
    pass_dash = stop_type == "pass" and depart_raw == EMPTY_MARKER

    speed_raw = (speed.raw or "").strip()
    if speed_raw == EMPTY_MARKER:
        speed_value = None  # positional rule applied in finalize
        speed_source = "not_printed"
    elif speed_raw.isdigit():
        speed_value = speed_raw  # keep "0" verbatim
        speed_source = "printed"
    elif speed_raw == "":
        speed_value = None
        speed_source = "empty"
        review.append("speed_blank")
    else:
        speed_value = None
        speed_source = "empty"
        review.append(f"speed_unrecognised:{speed_raw}")

    return Stop(
        seq=int(seq_cell.value),
        station_name=name,
        station_code=code,
        speed=Cell(speed_value, speed.raw, speed.page, speed.bbox, speed_source),
        arrive=Cell(arrive_value, arrive.raw, arrive.page, arrive.bbox, arrive_source),
        depart=Cell(depart_value, depart.raw, depart.page, depart.bbox, depart_source),
        note=note,
        stop_type=stop_type,
        info=["pass_row_with_dash_depart"] if pass_dash else [],
        needs_review=review,
        provenance={
            "page": block.page,
            "seq_bbox": seq_cell.bbox,
            "station_bbox": station_cell.bbox,
            "row_y": round(row[0].y_centre, 2),
        },
    )


def apply_positional_empty_rules(train: ParsedTrain) -> None:
    """Decide which ``-`` cells are structurally expected and which are doubts.

    Unflagged positions: Datang at the first seq, Berangkat at the last seq,
    Kecepatan at the last seq.
    """
    if not train.stops:
        return
    first_seq = train.stops[0].seq
    last_seq = train.stops[-1].seq

    def is_dash(cell: Cell) -> bool:
        return cell.raw.strip() == EMPTY_MARKER and cell.value is None

    for stop in train.stops:
        if is_dash(stop.arrive) and stop.seq != first_seq:
            stop.needs_review.append("arrive_dash_not_expected")
        # A pass row prints "Ls" with "-" in Berangkat as a matter of form, so a
        # dash there is only a doubt on a stopping row.
        if is_dash(stop.depart) and stop.seq != last_seq and stop.stop_type != "pass":
            stop.needs_review.append("depart_dash_not_expected")
        if is_dash(stop.speed) and stop.seq != last_seq:
            stop.needs_review.append("speed_dash_not_expected")


def apply_day_offsets(train: ParsedTrain) -> None:
    """Assign day_offset from consecutive times (Hard Rule 10).

    A time smaller than the previous time is the next day. A jump larger than
    ``MAX_PLAUSIBLE_GAP_SECONDS`` is implausible and flagged.
    """
    offset = 0
    previous: tuple[int, Stop] | None = None
    for stop in train.stops:
        reference = stop.depart.value or stop.arrive.value
        current = seconds_of(reference)
        if current is None:
            stop.day_offset = offset
            continue
        if previous is not None:
            previous_seconds, previous_stop = previous
            if current < previous_seconds:
                offset += 1
                gap = current + 24 * 3600 - previous_seconds
            else:
                gap = current - previous_seconds
            if gap > MAX_PLAUSIBLE_GAP_SECONDS:
                stop.needs_review.append(f"implausible_time_gap:{gap}s")
            if offset > 2:
                stop.needs_review.append(f"day_offset_exceeds_2:{offset}")
        stop.day_offset = offset
        previous = (current, stop)


def detect_completeness(train: ParsedTrain, page_range: tuple[int, int]) -> str:
    """Decide whether the trip's rows are all present in the loaded pages.

    Truncated when the last parsed station does not match the destination **and**
    the table reaches the bottom of the loaded page range. Otherwise unknown.
    """
    if not train.stops:
        return COMPLETENESS_UNKNOWN
    last_code = train.stops[-1].station_code
    destination = train.destination
    if last_code is not None and destination is not None and last_code == destination:
        return COMPLETENESS_COMPLETE

    last_page = max(stop.provenance.get("page", 0) for stop in train.stops)
    if last_page >= page_range[1]:
        return COMPLETENESS_TRUNCATED
    return COMPLETENESS_UNKNOWN


def parse_block(block: TableBlock) -> ParsedTrain | None:
    """Parse one table block into a ParsedTrain (finalisation happens later)."""
    train_no, name, origin, destination = parse_title(block)
    train = ParsedTrain(
        train_no=train_no,
        name=name,
        origin=origin,
        destination=destination,
        page=block.page,
        header_y=block.header_y,
        column_source=block.column_source,
        loaded_pages=[block.page],
    )
    if train_no is None:
        train.needs_review.append("train_header_unparsed")

    previous_seq: int | None = None
    for row in block.rows:
        stop = parse_stop(block, row)
        if stop is None:
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
    elif train.stops[0].seq != 1:
        train.info.append(f"does_not_start_at_seq_1:starts_{train.stops[0].seq}")

    return train


def parse_page(block_list: list[TableBlock]) -> list[ParsedTrain]:
    return [t for t in (parse_block(b) for b in block_list) if t is not None]


def merge_continuations(trains: list[ParsedTrain]) -> list[ParsedTrain]:
    """Attach a title-less block to the train it continues."""
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
            continued_from = train.stops[0].seq
            previous.stops.extend(train.stops)
            previous.notes.extend(train.notes)
            previous.loaded_pages.extend(train.loaded_pages)
            previous.info = [
                r for r in previous.info if not r.startswith("does_not_start_at_seq_1")
            ]
            previous.info.append(f"continued_on_page_{train.page}_from_seq_{continued_from}")
            continue
        merged.append(train)
    return merged


def finalize(trains: list[ParsedTrain], page_range: tuple[int, int]) -> list[ParsedTrain]:
    """Apply positional rules, day offsets, and completeness to every train."""
    for train in trains:
        apply_positional_empty_rules(train)
        apply_day_offsets(train)
        train.completeness = detect_completeness(train, page_range)
        if train.completeness == COMPLETENESS_TRUNCATED:
            train.info.append("truncated: last parsed station does not match destination")
    return trains


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
    return [{"text": text, "count": count} for text, count in sorted(seen.items())]
