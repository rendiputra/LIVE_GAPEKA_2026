"""Pure page-classification heuristics for the Gapeka 2026 PDF.

Everything in this module is a pure function of its arguments: no PDF library,
no file I/O, no clock. That keeps the rule table unit-testable without a PDF
and keeps the inventory output deterministic (ADR 001).

The rule order is fixed and documented in ``RULES``. The first matching rule
wins, and the rule number is recorded on every page so the report can show a
hit count per rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- page type enum (AGENTS.md section 6, Phase 0) ---------------------------
TYPE_TOC = "toc"
TYPE_TRAIN_TABLE = "train_table"
TYPE_LINE_TABLE = "line_table"
TYPE_GRAPHIC = "graphic"
TYPE_LEGEND = "legend"
TYPE_OTHER = "other"
TYPE_UNKNOWN = "unknown"

PAGE_TYPES: tuple[str, ...] = (
    TYPE_TOC,
    TYPE_TRAIN_TABLE,
    TYPE_LINE_TABLE,
    TYPE_GRAPHIC,
    TYPE_LEGEND,
    TYPE_OTHER,
    TYPE_UNKNOWN,
)

# --- section enum (ADR 001) --------------------------------------------------
SECTION_COVER = "cover"
SECTION_STRINGLINE = "stringline"
SECTION_INTERCITY = "intercity"
SECTION_KRL = "krl"
SECTION_FREIGHT = "freight"
SECTION_ROLLING_STOCK = "rolling_stock"
SECTION_SUMMARY = "summary"
SECTION_ANNEX = "annex"

SECTIONS: tuple[str, ...] = (
    SECTION_COVER,
    SECTION_STRINGLINE,
    SECTION_INTERCITY,
    SECTION_KRL,
    SECTION_FREIGHT,
    SECTION_ROLLING_STOCK,
    SECTION_SUMMARY,
    SECTION_ANNEX,
)

# --- confidence levels -------------------------------------------------------
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# --- rule table --------------------------------------------------------------
# Rule 1  no usable text (image-only / near-empty / title page)
# Rule 2  table of contents
# Rule 3  per-train stop table
# Rule 4  section divider page
# Rule 5  annex cover page
# Rule 6  multi-train summary table
# Rule 7  graphic / diagram (explicit marker)
# Rule 8  graphic / diagram (structural: landscape/oversized, no clock times)
# Rule 9  legend
# Rule 10 fallback -> unknown
#
# Rules 4 and 5 run before 6 and 7 because divider and cover pages quote the
# words "Lintas Pelayanan", "rangkaian" and "Grafik Perjalanan" in their own
# notes; the more specific page shape must win.
RULES: dict[int, str] = {
    1: "no usable text (image-only, near-empty, or title page)",
    2: "table-of-contents marker",
    3: "per-train stop-table header",
    4: "section divider page",
    5: "annex cover page",
    6: "multi-train summary marker",
    7: "graphic/diagram marker",
    8: "landscape/oversized page with no clock times",
    9: "legend marker",
    10: "no rule matched",
}

# A page with at most this many words and no clock times carries no table data.
NEAR_EMPTY_WORDS = 25
# Annex cover pages are short; body pages that merely mention "LAMPIRAN" are not.
ANNEX_COVER_MAX_WORDS = 100
# Rule 8 needs enough text to be a diagram rather than a blank page.
LANDSCAPE_MIN_WORDS = 50
# Rule 9 only applies to short key/legend pages.
LEGEND_MAX_WORDS = 300

TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
ANNEX_RE = re.compile(r"LAMPIRAN\s+(IV|III|II|I)\b")

TOC_MARKERS = ("DAFTAR ISI",)
# The Lampiran II index uses a different header than the "DAFTAR ISI" pages.
TOC_INDEX_MARKERS = ("URUT KA", "BRK", "DAT")
# Continuation pages of that index drop the header and carry only class names.
TOC_CLASS_KEYWORDS = ("EKSEKUTIF", "EKONOMI", "BISNIS", "COMMUTER LINE", "ARGO", "LOKAL", "FEEDER")
TOC_CONTINUATION_MIN_KEYWORDS = 3
TOC_CONTINUATION_MIN_DENSITY = 0.1
# The KRL timetable section opens with a differently shaped index header.
KRL_TOC_PREFIX = "DAFTAR ISI NOMOR KELAS KA NAMA KA LINTAS JAM HALAMAN URUT KA BRK DAT"
TRAIN_TABLE_MARKER = "STASIUN DAN PERHENTIAN"
LINE_TABLE_MARKERS = ("URUT KERETA API", "LINTAS PELAYANAN")
GRAPHIC_MARKERS = (
    "GRAFIK PERJALANAN",
    "GAMBAR GRAFIS",
    "RANGKAIAN",
    "SIAP GUNA",
    "KAPASITAS LINTAS",
    "DUDUK BERDIRI",
    "TS UNIT",
    "JALUR GANDA",
    "EFF OPS",
)
ANNEX_COVER_MARKERS = ("LAMPIRAN", "KEPUTUSAN DIREKTUR JENDERAL")
DIVIDER_MARKERS = ("DAFTAR WAKTU", "ISI:")
LEGEND_MARKERS = ("UNTUK LINTAS", "KETERANGAN")

ANNEX_SECTION_BY_NUMERAL = {
    "I": SECTION_STRINGLINE,
    "II": SECTION_INTERCITY,
    "III": SECTION_ROLLING_STOCK,
    "IV": SECTION_SUMMARY,
}


@dataclass(frozen=True)
class PageSignals:
    """Everything the classifier is allowed to look at for one page."""

    page: int
    width_pt: float
    height_pt: float
    rotation: int
    word_count: int
    image_count: int
    text: str  # whitespace-normalised and upper-cased
    time_token_count: int
    table_header_count: int
    train_header_count: int = 0
    train_any_count: int = 0
    train_lintas_count: int = 0
    time_with_seconds: int = 0
    time_minutes_only: int = 0
    index_number_count: int = 0
    printed_page: str | None = None

    @property
    def orientation(self) -> str:
        return "landscape" if self.width_pt > self.height_pt else "portrait"

    @property
    def is_oversized(self) -> bool:
        """The stringline annex is printed on pages far larger than A4."""
        return self.width_pt > 1000 or self.height_pt > 1000

    @property
    def time_density(self) -> float:
        """Clock-time tokens per word. Separates tables from diagrams."""
        if self.word_count == 0:
            return 0.0
        return self.time_token_count / self.word_count


@dataclass(frozen=True)
class Classification:
    type: str
    confidence: str
    rule: int
    reasons: tuple[str, ...]


def _result(page_type: str, confidence: str, rule: int, *reasons: str) -> Classification:
    return Classification(type=page_type, confidence=confidence, rule=rule, reasons=tuple(reasons))


def _is_annex_cover(s: PageSignals) -> bool:
    return s.word_count < ANNEX_COVER_MAX_WORDS and all(m in s.text for m in ANNEX_COVER_MARKERS)


def classify_page(s: PageSignals) -> Classification:
    """Classify one page. First matching rule wins."""
    t = s.text

    # Rule 1 -- no usable text.
    if s.word_count == 0:
        return _result(TYPE_OTHER, CONFIDENCE_HIGH, 1, "no extractable text")
    if s.word_count <= NEAR_EMPTY_WORDS and s.time_token_count == 0:
        return _result(
            TYPE_OTHER,
            CONFIDENCE_HIGH,
            1,
            f"only {s.word_count} words and no clock times",
        )

    # Rule 2 -- table of contents.
    if any(m in t for m in TOC_MARKERS):
        return _result(TYPE_TOC, CONFIDENCE_HIGH, 2, "contains 'DAFTAR ISI'")
    if all(m in t for m in TOC_INDEX_MARKERS):
        return _result(TYPE_TOC, CONFIDENCE_HIGH, 2, "contains index header 'URUT KA / BRK / DAT'")
    class_hits = sum(1 for k in TOC_CLASS_KEYWORDS if k in t)
    if (
        class_hits >= TOC_CONTINUATION_MIN_KEYWORDS
        and s.time_density >= TOC_CONTINUATION_MIN_DENSITY
        and TRAIN_TABLE_MARKER not in t
        and "URUT KERETA API" not in t
    ):
        return _result(
            TYPE_TOC,
            CONFIDENCE_MEDIUM,
            2,
            f"index continuation: {class_hits} class keywords, time density {s.time_density:.2f}",
        )

    # Rule 3 -- per-train stop table.
    if TRAIN_TABLE_MARKER in t:
        return _result(
            TYPE_TRAIN_TABLE,
            CONFIDENCE_HIGH,
            3,
            f"contains '{TRAIN_TABLE_MARKER}'",
            f"{s.table_header_count} table header(s) on page",
        )

    # Rule 4 -- section divider page. Runs before rules 6/7 because divider
    # pages quote "Lintas Pelayanan" and "rangkaian" in their notes.
    if all(m in t for m in DIVIDER_MARKERS):
        return _result(TYPE_OTHER, CONFIDENCE_HIGH, 4, "contains 'DAFTAR WAKTU' + 'ISI:'")

    # Rule 5 -- annex cover page.
    if _is_annex_cover(s):
        return _result(
            TYPE_OTHER,
            CONFIDENCE_HIGH,
            5,
            "short page with 'LAMPIRAN' + 'KEPUTUSAN DIREKTUR JENDERAL'",
        )

    # Rule 6 -- multi-train summary table.
    for marker in LINE_TABLE_MARKERS:
        if marker in t:
            return _result(TYPE_LINE_TABLE, CONFIDENCE_HIGH, 6, f"contains '{marker}'")

    # Rule 7 -- graphic/diagram with an explicit marker (annex covers excluded).
    if not _is_annex_cover(s):
        for marker in GRAPHIC_MARKERS:
            if marker in t:
                return _result(TYPE_GRAPHIC, CONFIDENCE_HIGH, 7, f"contains '{marker}'")

    # Rule 8 -- structural graphic: landscape or oversized, no clock times, enough text.
    if (
        (s.orientation == "landscape" or s.is_oversized)
        and s.time_token_count == 0
        and s.word_count > LANDSCAPE_MIN_WORDS
    ):
        return _result(
            TYPE_GRAPHIC,
            CONFIDENCE_MEDIUM,
            8,
            f"{s.orientation} page with no clock times",
            f"{s.word_count} words",
        )

    # Rule 9 -- legend.
    if s.word_count < LEGEND_MAX_WORDS and any(m in t for m in LEGEND_MARKERS):
        return _result(TYPE_LEGEND, CONFIDENCE_MEDIUM, 9, "short page with legend markers")

    # Rule 10 -- fallback.
    return _result(TYPE_UNKNOWN, CONFIDENCE_LOW, 10, "no rule matched")


def section_transition(s: PageSignals) -> str | None:
    """Return the section that starts on this page, or None to keep the current one.

    Boundaries are derived from content markers only -- never from page numbers.
    """
    t = s.text

    match = ANNEX_RE.search(t)
    if match and s.word_count < ANNEX_COVER_MAX_WORDS:
        return ANNEX_SECTION_BY_NUMERAL[match.group(1)]

    if t.startswith(KRL_TOC_PREFIX):
        return SECTION_KRL

    # The freight index reuses the "URUT KA BRK DAT" header but lists KA barang.
    if t.startswith("URUT KA BRK DAT") and "BARANG" in t:
        return SECTION_FREIGHT

    if "KAPASITAS LINTAS" in t and s.word_count < ANNEX_COVER_MAX_WORDS:
        return SECTION_ANNEX

    return None


def assign_sections(pages: list[PageSignals]) -> list[str]:
    """Walk pages in order and assign a section to each one."""
    current = SECTION_COVER
    out: list[str] = []
    for s in pages:
        new = section_transition(s)
        if new is not None:
            current = new
        out.append(current)
    return out


def assign_books(pages: list[PageSignals], sections: list[str]) -> list[int]:
    """Number the books inside a section, 1-based.

    A new book starts at a section divider whose printed page is 1, i.e. where
    the document's own numbering restarts. The intercity section is really two
    books (ADR 001): book 1 is intercity, book 2 is local/commuter services.
    Dividers that do not reset numbering start a new *series*, not a new book.
    """
    current_section = SECTION_COVER
    book = 0
    out: list[int] = []
    for s, section in zip(pages, sections, strict=True):
        if section != current_section:
            current_section = section
            book = 0
        if all(m in s.text for m in DIVIDER_MARKERS) and s.printed_page == "1":
            book += 1
        out.append(max(1, book))
    return out


def derive_subtype(page_type: str, section: str, s: PageSignals, book: int = 1) -> str:
    """Subtype is a free-form label; it never changes the 7-value type enum."""
    t = s.text

    if page_type == TYPE_TRAIN_TABLE:
        if section == SECTION_KRL:
            return "krl_train_table"
        if section == SECTION_FREIGHT:
            return "freight_train_table"
        if section == SECTION_INTERCITY:
            return "local_train_table" if book >= 2 else "intercity_train_table"
        return "train_table"

    if page_type == TYPE_TOC:
        if section == SECTION_KRL:
            return "toc_krl"
        if section == SECTION_FREIGHT:
            return "toc_freight"
        if section == SECTION_INTERCITY:
            return "toc_local" if book >= 2 else "toc_intercity"
        return "toc"

    if page_type == TYPE_LINE_TABLE:
        if "URUT KERETA API" in t:
            return "summary_by_train"
        if "LINTAS PELAYANAN" in t:
            return "summary_by_line"
        return "line_table"

    if page_type == TYPE_GRAPHIC:
        if "GRAFIK PERJALANAN" in t or "GAMBAR GRAFIS" in t or "JALUR GANDA" in t:
            return "stringline_chart"
        if section == SECTION_STRINGLINE:
            return "stringline_chart"
        if "KAPASITAS LINTAS" in t:
            return "capacity_chart"
        if "JARAK ANTAR STASIUN" in t:
            return "distance_table"
        if section == SECTION_ANNEX and len(re.findall(r"\d{1,3},\d{3}", t)) >= 5:
            return "distance_table"
        if "DUDUK BERDIRI" in t:
            return "seat_map"
        if "SIAP GUNA" in t or "RANGKAIAN" in t or "TS UNIT" in t:
            return "rolling_stock"
        return "graphic"

    if page_type == TYPE_OTHER:
        if s.word_count == 0:
            return "image_only"
        if s.word_count <= 5:
            return "near_empty"
        if s.word_count <= NEAR_EMPTY_WORDS and s.time_token_count == 0:
            return "title_page"
        if _is_annex_cover(s):
            return "cover_decree"
        if all(m in t for m in DIVIDER_MARKERS):
            return "section_divider"
        return "other"

    if page_type == TYPE_LEGEND:
        return "legend"

    return "unknown"
