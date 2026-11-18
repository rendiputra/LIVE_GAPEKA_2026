"""Unit tests for the pure classifier. No PDF is opened here."""

from __future__ import annotations

import pytest

from pipeline.classify import (
    SECTION_ANNEX,
    SECTION_COVER,
    SECTION_FREIGHT,
    SECTION_INTERCITY,
    SECTION_KRL,
    SECTION_ROLLING_STOCK,
    SECTION_STRINGLINE,
    SECTION_SUMMARY,
    TYPE_GRAPHIC,
    TYPE_LEGEND,
    TYPE_LINE_TABLE,
    TYPE_OTHER,
    TYPE_TOC,
    TYPE_TRAIN_TABLE,
    TYPE_UNKNOWN,
    PageSignals,
    assign_sections,
    classify_page,
    derive_subtype,
    section_transition,
)


def signals(
    text: str = "",
    *,
    page: int = 1,
    words: int | None = None,
    times: int = 0,
    width: float = 595.0,
    height: float = 842.0,
    tables: int = 0,
) -> PageSignals:
    """Build a PageSignals for a normal, text-bearing page.

    ``words`` defaults to 200 so that short test strings are not accidentally
    caught by rule 1 (the near-empty-page guard). Pass ``words=`` explicitly
    when the test is about that guard.
    """
    normalised = " ".join(text.upper().split())
    return PageSignals(
        page=page,
        width_pt=width,
        height_pt=height,
        rotation=0,
        word_count=200 if words is None else words,
        image_count=0,
        text=normalised,
        time_token_count=times,
        table_header_count=tables,
    )


# --- rule 1: no usable text --------------------------------------------------


def test_zero_words_is_image_only():
    result = classify_page(signals("", words=0))
    assert result.type == TYPE_OTHER
    assert result.rule == 1
    assert result.confidence == "high"


def test_few_words_without_times_is_a_title_page():
    result = classify_page(signals("KAPASITAS LINTAS BERLAKU PADA GAPEKA 2026", words=8))
    assert result.type == TYPE_OTHER
    assert result.rule == 1


def test_few_words_with_times_is_not_swallowed_by_rule_1():
    result = classify_page(signals("KA 1 08:00 09:00", words=5, times=2))
    assert result.rule != 1


# --- rule 2: table of contents ----------------------------------------------


def test_daftar_isi_is_toc():
    result = classify_page(signals("DAFTAR ISI 1 ARGO ANGGREK SBI-GMR 08:15 16:12"))
    assert result.type == TYPE_TOC
    assert result.rule == 2


def test_index_header_without_daftar_isi_is_toc():
    result = classify_page(signals("URUT KA BRK DAT 1 1 ARGO ANGGREK SBI-GMR 08:15"))
    assert result.type == TYPE_TOC
    assert result.rule == 2


def test_index_continuation_with_class_keywords_is_toc():
    text = "61 414 EKONOMI LOKAL COMMUTER LINE BANDUNG RAYA PDL-CCL 03:55 05:27"
    result = classify_page(signals(text, words=10, times=2))
    assert result.type == TYPE_TOC
    assert result.confidence == "medium"


def test_summary_table_is_not_mistaken_for_a_toc_continuation():
    text = (
        "WAKTU PERJALANAN URUT KERETA API BERANGKAT DATANG JAM NOMOR JENIS KA "
        "EKSEKUTIF EKONOMI BISNIS 08:00 09:00"
    )
    result = classify_page(signals(text, times=2))
    assert result.type == TYPE_LINE_TABLE


# --- rule 3: per-train stop table -------------------------------------------


def test_stasiun_dan_perhentian_is_train_table():
    result = classify_page(signals("No. Stasiun dan Perhentian Datang Berangkat", tables=1))
    assert result.type == TYPE_TRAIN_TABLE
    assert result.rule == 3


# --- rule 4: section divider -------------------------------------------------


def test_divider_wins_over_the_words_it_quotes():
    # Real divider pages quote "Lintas Pelayanan" and "rangkaian" in their notes.
    text = (
        "PT. KERETA API INDONESIA DAFTAR WAKTU ISI: KA 1 (Anggrek) "
        "Lintas Pelayanan SBI - GMR rangkaian kereta"
    )
    result = classify_page(signals(text))
    assert result.type == TYPE_OTHER
    assert result.rule == 4


# --- rule 5: annex cover -----------------------------------------------------


def test_annex_cover_is_other_not_graphic():
    text = (
        "LAMPIRAN I KEPUTUSAN DIREKTUR JENDERAL PERKERETAAPIAN NOMOR KP-DJKA 116 "
        "TAHUN 2026 TENTANG GRAFIK PERJALANAN KERETA API GAMBAR GRAFIS"
    )
    result = classify_page(signals(text, words=40))
    assert result.type == TYPE_OTHER
    assert result.rule == 5


# --- rule 6: multi-train summary --------------------------------------------


def test_lintas_pelayanan_is_line_table():
    result = classify_page(signals("KA 842 (Commuter Line BST) Lintas Pelayanan DU - BST"))
    assert result.type == TYPE_LINE_TABLE
    assert result.rule == 6


# --- rule 7: graphic marker --------------------------------------------------


def test_grafik_perjalanan_is_graphic():
    result = classify_page(signals("GRAFIK PERJALANAN KERETA API JALUR GANDA TG - CU"))
    assert result.type == TYPE_GRAPHIC
    assert result.rule == 7


# --- rule 8: structural graphic ---------------------------------------------


def test_landscape_page_without_times_is_graphic():
    result = classify_page(
        signals("KPB-AC KRL SEMEN PTK PARCEL " * 20, words=100, width=842, height=595)
    )
    assert result.type == TYPE_GRAPHIC
    assert result.rule == 8
    assert result.confidence == "medium"


def test_oversized_portrait_page_without_times_is_graphic():
    result = classify_page(
        signals("CIREBON PRUJAKAN PRUPUK " * 20, words=100, width=1843, height=2835)
    )
    assert result.type == TYPE_GRAPHIC
    assert result.rule == 8


def test_landscape_page_with_times_is_not_rule_8():
    result = classify_page(
        signals("WAKTU PERJALANAN 08:00 09:00 " * 20, words=100, times=40, width=842, height=595)
    )
    assert result.rule != 8


# --- rule 9: legend ----------------------------------------------------------


def test_short_legend_page_is_legend():
    result = classify_page(signals("KETERANGAN UNTUK LINTAS JAKK - MRI", words=10, times=1))
    assert result.type == TYPE_LEGEND
    assert result.rule == 9


# --- rule 10: fallback -------------------------------------------------------


def test_unmatched_page_is_unknown():
    result = classify_page(signals("some prose that matches nothing at all", words=40))
    assert result.type == TYPE_UNKNOWN
    assert result.rule == 10
    assert result.confidence == "low"


# --- derived properties ------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(595, 842, "portrait"), (842, 595, "landscape"), (595, 595, "portrait")],
)
def test_orientation(width, height, expected):
    assert signals("", width=width, height=height).orientation == expected


def test_time_density_is_zero_for_empty_page():
    assert signals("", words=0).time_density == 0.0


def test_time_density_is_times_over_words():
    assert signals("", words=100, times=25).time_density == pytest.approx(0.25)


# --- section transitions -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "words", "expected"),
    [
        ("LAMPIRAN I KEPUTUSAN DIREKTUR JENDERAL GRAFIK PERJALANAN", 40, SECTION_STRINGLINE),
        ("LAMPIRAN II KEPUTUSAN DIREKTUR JENDERAL BUKU PERJALANAN", 40, SECTION_INTERCITY),
        ("LAMPIRAN III KEPUTUSAN DIREKTUR JENDERAL SARANA", 40, SECTION_ROLLING_STOCK),
        ("LAMPIRAN IV KEPUTUSAN DIREKTUR JENDERAL PENOMORAN", 40, SECTION_SUMMARY),
        (
            "DAFTAR ISI NOMOR KELAS KA NAMA KA LINTAS JAM HALAMAN URUT KA BRK DAT",
            40,
            SECTION_KRL,
        ),
        ("URUT KA BRK DAT 1 343 BARANG HANTARAN PARCEL", 40, SECTION_FREIGHT),
        ("KAPASITAS LINTAS BERLAKU PADA GAPEKA 2026", 20, SECTION_ANNEX),
    ],
)
def test_section_transitions(text, words, expected):
    assert section_transition(signals(text, words=words)) == expected


def test_lampiran_ii_does_not_match_lampiran_i():
    # "LAMPIRAN I" is a prefix of "LAMPIRAN II"; the regex must not confuse them.
    assert section_transition(signals("LAMPIRAN II KEPUTUSAN", words=40)) == SECTION_INTERCITY


def test_body_page_mentioning_lampiran_does_not_switch_section():
    assert section_transition(signals("LAMPIRAN I " * 50, words=200)) is None


def test_capacity_mention_inside_a_long_toc_does_not_switch_section():
    text = "NO URAIAN HAL 1 DAFTAR ISI 1 26 KAPASITAS LINTAS 40 " + "X " * 200
    assert section_transition(signals(text, words=220)) is None


def test_assign_sections_walks_in_order():
    pages = [
        signals("", words=0, page=1),
        signals("LAMPIRAN I KEPUTUSAN DIREKTUR JENDERAL GRAFIK PERJALANAN", words=40, page=2),
        signals("GRAFIK PERJALANAN", page=3),
        signals("LAMPIRAN II KEPUTUSAN DIREKTUR JENDERAL", words=40, page=4),
        signals("No. Stasiun dan Perhentian", page=5),
    ]
    assert assign_sections(pages) == [
        SECTION_COVER,
        SECTION_STRINGLINE,
        SECTION_STRINGLINE,
        SECTION_INTERCITY,
        SECTION_INTERCITY,
    ]


# --- subtypes ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("page_type", "section", "text", "expected"),
    [
        (TYPE_TRAIN_TABLE, SECTION_INTERCITY, "", "intercity_train_table"),
        (TYPE_TRAIN_TABLE, SECTION_KRL, "", "krl_train_table"),
        (TYPE_TRAIN_TABLE, SECTION_FREIGHT, "", "freight_train_table"),
        (TYPE_TOC, SECTION_KRL, "", "toc_krl"),
        (TYPE_TOC, SECTION_FREIGHT, "", "toc_freight"),
        (TYPE_TOC, SECTION_INTERCITY, "", "toc_intercity"),
        (TYPE_LINE_TABLE, SECTION_SUMMARY, "URUT KERETA API", "summary_by_train"),
        (TYPE_LINE_TABLE, SECTION_KRL, "LINTAS PELAYANAN", "summary_by_line"),
        (TYPE_GRAPHIC, SECTION_STRINGLINE, "", "stringline_chart"),
        (TYPE_GRAPHIC, SECTION_ANNEX, "KAPASITAS LINTAS", "capacity_chart"),
        (TYPE_GRAPHIC, SECTION_ANNEX, "9,241 15,722 19,297 6,481 10,056 3,575", "distance_table"),
        (TYPE_GRAPHIC, SECTION_ROLLING_STOCK, "DUDUK BERDIRI", "seat_map"),
        (TYPE_GRAPHIC, SECTION_ROLLING_STOCK, "SIAP GUNA", "rolling_stock"),
        (TYPE_OTHER, SECTION_COVER, "", "image_only"),
        (TYPE_OTHER, SECTION_INTERCITY, "DAFTAR WAKTU ISI:", "section_divider"),
        (TYPE_LEGEND, SECTION_STRINGLINE, "", "legend"),
        (TYPE_UNKNOWN, SECTION_COVER, "", "unknown"),
    ],
)
def test_derive_subtype(page_type, section, text, expected):
    s = signals(text, words=0 if expected == "image_only" else 40)
    assert derive_subtype(page_type, section, s) == expected
