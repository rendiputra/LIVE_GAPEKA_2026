"""Geometry-driven parser for Gapeka per-train stop tables.

Hard Rule 11: rows and columns are rebuilt from x/y coordinates only. The PDF
text stream is never trusted for ordering — on KRL pages it emits ``Berangkat``
before ``Datang``.

Column boundaries come from the table's own **ruling lines** when they are
present, because those are the document's own definition of a cell. When a page
has no ruling lines, boundaries fall back to midpoints between header labels.
Neither path contains a hardcoded x value.

Pipeline for one page:

1. read vertical ruling lines (fallback: header-label midpoints);
2. find every table header (``No.`` + ``Stasiun dan Perhentian``);
3. split the page into table blocks at header y-positions;
4. map each column span to a semantic key using the header words it contains;
5. group words into rows by y (tolerance configurable);
6. assign each word to a column by its x-centre;
7. attach provenance (page + bbox) to every emitted value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

COL_NO = "no"
COL_STATION = "station"
COL_SPEED = "speed"
COL_ARRIVE = "arrive"
COL_DEPART = "depart"
COL_NOTE = "keterangan"

COLUMN_ORDER = [COL_NO, COL_STATION, COL_SPEED, COL_ARRIVE, COL_DEPART, COL_NOTE]

DEFAULT_Y_TOLERANCE = 4.0

# Header label -> semantic key. Matched on the extracted label text.
HEADER_LABELS: dict[str, str] = {
    "NO": COL_NO,
    "STASIUN": COL_STATION,
    "DAN": COL_STATION,
    "PERHENTIAN": COL_STATION,
    "KECEPATAN": COL_SPEED,
    "MAKSIMUM": COL_SPEED,
    "(KM/JAM)": COL_SPEED,
    "DATANG": COL_ARRIVE,
    "BERANGKAT": COL_DEPART,
    "KETERANGAN": COL_NOTE,
}


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int
    word: int

    @property
    def x_centre(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_centre(self) -> float:
        return (self.y0 + self.y1) / 2

    def bbox(self) -> list[float]:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]


def words_from_raw(payload: dict) -> list[Word]:
    """Convert a raw page payload into Word objects."""
    return [
        Word(
            x0=row[0],
            y0=row[1],
            x1=row[2],
            y1=row[3],
            text=row[4],
            block=row[5],
            line=row[6],
            word=row[7],
        )
        for row in payload["words"]
    ]


def label(text: str) -> str:
    return text.strip().upper().rstrip(".")


@dataclass
class Column:
    key: str
    x0: float
    x1: float
    source: str = "ruling"

    def contains(self, x: float) -> bool:
        return self.x0 <= x < self.x1

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "x0": None if self.x0 == float("-inf") else round(self.x0, 2),
            "x1": None if self.x1 == float("inf") else round(self.x1, 2),
            "source": self.source,
        }


@dataclass
class TableBlock:
    """One table on a page: its column geometry and the words beneath it."""

    page: int
    header_y: float
    columns: list[Column]
    rows: list[list[Word]]
    bottom_y: float
    title_words: list[Word] = field(default_factory=list)
    column_source: str = "ruling"

    def cell(self, row: list[Word], key: str) -> list[Word]:
        column = next((c for c in self.columns if c.key == key), None)
        if column is None:
            return []
        return [w for w in row if column.contains(w.x_centre)]

    def cell_text(self, row: list[Word], key: str) -> str:
        return " ".join(w.text for w in self.cell(row, key)).strip()


# --- header detection -------------------------------------------------------


def find_header_rows(words: list[Word]) -> list[float]:
    """Return the y of every header row (one that carries both No. and Stasiun)."""
    anchors = [w for w in words if label(w.text) in ("NO", "STASIUN")]
    candidate_ys: list[float] = []
    for anchor in sorted(anchors, key=lambda w: w.y0):
        if not candidate_ys or anchor.y0 - candidate_ys[-1] > 10:
            candidate_ys.append(anchor.y0)

    confirmed: list[float] = []
    for y in candidate_ys:
        on_line = {label(w.text) for w in words if abs(w.y0 - y) < 3}
        if "NO" in on_line and "STASIUN" in on_line:
            confirmed.append(y)
    return confirmed


def header_words(words: list[Word], header_y: float) -> list[Word]:
    """Words belonging to a (possibly three-line) header block.

    The header is identified by its three known labels appearing in sequence:
    ``Kecepatan`` / ``Maksimum`` / ``(Km/Jam)``. Only those labels are taken, so
    the first body row (which sits immediately below) is never absorbed.
    """
    header_labels = set(HEADER_LABELS)
    block: list[Word] = []
    for word in words:
        if not (header_y - 2 <= word.y0 <= header_y + 30):
            continue
        if label(word.text) in header_labels:
            block.append(word)
    return block


# --- column derivation ------------------------------------------------------


def columns_from_rulings(verticals: list[float], header: list[Word]) -> list[Column] | None:
    """Build columns from the table's own ruling lines.

    Each header label is assigned to the span it sits in; the semantic key comes
    from the label. Returns ``None`` if the header does not map cleanly.
    """
    if len(verticals) < 2:
        return None

    spans = list(zip(verticals, verticals[1:], strict=False))
    keys: dict[int, str] = {}
    for word in header:
        text = label(word.text)
        key = HEADER_LABELS.get(text)
        if key is None:
            continue
        for index, (x0, x1) in enumerate(spans):
            if x0 <= word.x_centre < x1:
                keys.setdefault(index, key)
                break

    if sorted(set(keys.values())) != sorted(COLUMN_ORDER):
        return None

    columns: list[Column] = []
    for index, (x0, x1) in enumerate(spans):
        key = keys.get(index)
        if key is None:
            continue
        columns.append(Column(key=key, x0=x0, x1=x1, source="ruling"))
    return columns if len(columns) == len(COLUMN_ORDER) else None


def columns_from_header(header: list[Word]) -> list[Column]:
    """Fallback: midpoints between adjacent header labels."""
    spans: dict[str, tuple[float, float]] = {}
    for word in header:
        key = HEADER_LABELS.get(label(word.text))
        if key is None:
            continue
        low, high = spans.get(key, (word.x0, word.x1))
        spans[key] = (min(low, word.x0), max(high, word.x1))

    missing = [k for k in COLUMN_ORDER if k not in spans]
    if missing:
        raise ValueError(f"header is missing column(s): {missing}")

    columns: list[Column] = []
    for index, key in enumerate(COLUMN_ORDER):
        left = (
            float("-inf") if index == 0 else (spans[COLUMN_ORDER[index - 1]][1] + spans[key][0]) / 2
        )
        right = (
            float("inf")
            if index == len(COLUMN_ORDER) - 1
            else (spans[key][1] + spans[COLUMN_ORDER[index + 1]][0]) / 2
        )
        columns.append(Column(key=key, x0=left, x1=right, source="header"))
    return columns


# --- row grouping -----------------------------------------------------------


def group_rows(
    words: list[Word],
    tolerance: float = DEFAULT_Y_TOLERANCE,
    no_column: tuple[float, float] | None = None,
    station_column: tuple[float, float] | None = None,
) -> list[list[Word]]:
    """Group words into rows.

    When ``no_column`` (the x-band of the ``No.`` column) is supplied, rows are
    **anchored on the sequence numbers**. That is required because a station name
    may wrap onto the line *above* its own sequence number (e.g. "Yogyakarta /
    International" on Book 2), so a plain y-centre grouping splits the row and
    the name is lost.

    Without an anchor the function falls back to y-centre grouping.
    """
    if not words:
        return []

    if no_column is not None:
        x0, x1 = no_column
        anchors = sorted(
            (w for w in words if x0 <= w.x0 < x1 and w.text.strip().isdigit()),
            key=lambda w: w.y_centre,
        )
        if anchors:
            rows: list[list[Word]] = []
            boundaries = [
                (anchors[i].y_centre + anchors[i + 1].y_centre) / 2 for i in range(len(anchors) - 1)
            ]
            # The first band extends above its anchor far enough to capture a
            # wrapped station name printed above the sequence number.
            head_margin = max(tolerance, 24.0)
            bounds = [anchors[0].y_centre - head_margin] + boundaries
            tops = list(bounds)
            bottoms = boundaries + [float("inf")]
            for top, bottom in zip(tops, bottoms, strict=True):
                row = [w for w in words if top <= w.y_centre < bottom]
                if row:
                    rows.append(sorted(row, key=lambda w: w.x0))

            # A station name may wrap over three lines and straddle the band
            # boundaries (e.g. "Yogyakarta / International / Airport (YIA)").
            # Words in the station column are therefore assigned to their NEAREST
            # sequence anchor instead of to the band they fall in. This is a
            # property of the column, not of any particular train.
            if station_column is not None:
                sx0, sx1 = station_column
                anchor_ys = [a.y_centre for a in anchors]
                rows = [list(r) for r in rows]
                for word in words:
                    if not (sx0 <= word.x0 < sx1):
                        continue
                    nearest = min(
                        range(len(anchor_ys)),
                        key=lambda i: abs(word.y_centre - anchor_ys[i]),
                    )
                    # Only reassign when it is genuinely closer to another anchor.
                    current = next((i for i, r in enumerate(rows) if word in r), None)
                    if current is not None and current != nearest:
                        rows[current].remove(word)
                        rows[nearest].append(word)
                rows = [sorted(r, key=lambda w: w.x0) for r in rows if r]
            return rows

    ordered = sorted(words, key=lambda w: (w.y_centre, w.x0))
    rows = []
    for word in ordered:
        if rows and abs(word.y_centre - _row_y_centre(rows[-1])) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda w: w.x0) for row in rows]


def _row_y_centre(row: list[Word]) -> float:
    return sum(w.y_centre for w in row) / len(row)


def header_bottom(words: list[Word], header_y: float) -> float:
    """The y where the header block ends and body rows begin.

    The header is three lines tall (``Kecepatan / Maksimum / (Km/Jam)``), so the
    body starts below the *deepest* header word, not at a fixed offset.
    """
    block = header_words(words, header_y)
    return max((w.y1 for w in block), default=header_y + 10) + 1.0


# --- table splitting --------------------------------------------------------


def split_tables(
    words: list[Word],
    page: int,
    verticals: list[float] | None = None,
    tolerance: float = DEFAULT_Y_TOLERANCE,
) -> list[TableBlock]:
    """Split a page into table blocks at each header row."""
    header_ys = find_header_rows(words)
    if not header_ys:
        return []

    blocks: list[TableBlock] = []
    page_height = max((w.y1 for w in words), default=0.0)
    margin_top = page_height * 0.95
    for index, header_y in enumerate(header_ys):
        body_top = header_bottom(words, header_y)
        # The next table's title sits ~40pt above its header; stop the body before
        # it, otherwise the title words are parsed as stop rows.
        body_bottom = header_ys[index + 1] - 40 if index + 1 < len(header_ys) else margin_top
        header = header_words(words, header_y)

        columns = columns_from_rulings(verticals or [], header)
        source = "ruling"
        if columns is None:
            try:
                columns = columns_from_header(header)
            except ValueError:
                continue
            source = "header"

        body = [w for w in words if body_top <= w.y0 < body_bottom]
        no_col = next((c for c in columns if c.key == COL_NO), None)
        no_band = (no_col.x0, no_col.x1) if no_col is not None else None
        station_col = next((c for c in columns if c.key == COL_STATION), None)
        station_band = (station_col.x0, station_col.x1) if station_col is not None else None
        blocks.append(
            TableBlock(
                page=page,
                header_y=header_y,
                columns=columns,
                rows=group_rows(body, tolerance, no_band, station_band),
                bottom_y=body_bottom,
                title_words=[w for w in words if header_y - 40 <= w.y0 < header_y - 2],
                column_source=source,
            )
        )
    return blocks
