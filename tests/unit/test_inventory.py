"""End-to-end tests for the inventory extractor, using a synthetic PDF.

No Gapeka content is committed: the fixture PDF is built at test time with
PyMuPDF, so the extraction path is exercised without shipping the source.
"""

from __future__ import annotations

import json

import pymupdf
import pytest

from pipeline.inventory import (
    build_inventory,
    extract_printed_page,
    extract_signals,
    main,
    normalise,
    summarise,
    write_json,
)

TRAIN_TABLE_TEXT = [
    "KA 249 (Kaligung) Relasi SMC - BB",
    "No. Stasiun dan Perhentian Kecepatan Maksimum (Km/Jam) Datang Berangkat Keterangan",
    "1 Semarang Poncol (SMC) 100 - 08:40:00",
    "2 Jerakah (JRK) 100 Ls 08:47:00",
    "3 Brebes (BB) - 11:03:00 -",
]

TOC_TEXT = ["DAFTAR ISI", "1 1 ARGO ANGGREK SBI-GMR 08:15 16:12 2"]

GRAPHIC_TEXT = ["KPB-AC KRL SEMEN PTK PARCEL"] * 12


def _write_page(doc: pymupdf.Document, lines: list[str], *, width=595, height=842, number=None):
    page = doc.new_page(width=width, height=height)
    y = 80
    for line in lines:
        page.insert_text((60, y), line, fontsize=9)
        y += 14
    if number is not None:
        page.insert_text((width / 2 - 6, height - 20), str(number), fontsize=9)
    return page


@pytest.fixture()
def synthetic_pdf(tmp_path):
    path = tmp_path / "synthetic.pdf"
    doc = pymupdf.open()
    _write_page(doc, TRAIN_TABLE_TEXT, number=1)
    _write_page(doc, TOC_TEXT, number=2)
    _write_page(doc, GRAPHIC_TEXT, width=842, height=595, number=3)
    _write_page(doc, [])  # image-only stand-in: no text at all
    doc.save(path)
    doc.close()
    return path


def test_normalise_collapses_whitespace_and_uppercases():
    assert normalise("  a\n b\tc ") == "A B C"


def test_extract_printed_page_reads_the_bottom_margin():
    doc = pymupdf.open()
    page = _write_page(doc, ["hello"], number=42)
    words = page.get_text("words")
    assert extract_printed_page(words, page.rect.height) == "42"
    doc.close()


def test_extract_printed_page_ignores_table_cells():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # A row of numbers near the bottom, but not alone on its own line.
    page.insert_text((60, 800), "100 08:40:00 08:47:00 11:03:00", fontsize=9)
    words = page.get_text("words")
    assert extract_printed_page(words, page.rect.height) is None
    doc.close()


def test_extract_printed_page_returns_none_when_absent():
    doc = pymupdf.open()
    page = _write_page(doc, ["hello"])
    assert extract_printed_page(page.get_text("words"), page.rect.height) is None
    doc.close()


def test_extract_signals_counts_words_times_and_tables(synthetic_pdf):
    doc = pymupdf.open(synthetic_pdf)
    s = extract_signals(doc, 0)
    doc.close()

    assert s.page == 1
    assert s.word_count > 0
    assert s.time_token_count == 3  # 08:40, 08:47, 11:03
    assert s.table_header_count == 1
    assert s.train_header_count == 1
    assert s.printed_page == "1"
    assert s.orientation == "portrait"


def test_build_inventory_classifies_every_page(synthetic_pdf):
    inventory = build_inventory(synthetic_pdf)
    pages = inventory["pages"]

    assert inventory["source"]["page_count"] == 4
    assert len(pages) == 4
    assert [p["page"] for p in pages] == [1, 2, 3, 4]

    assert pages[0]["type"] == "train_table"
    assert pages[1]["type"] == "toc"
    assert pages[2]["type"] == "graphic"
    assert pages[2]["orientation"] == "landscape"
    assert pages[3]["type"] == "other"
    assert pages[3]["text_extractable"] is False


def test_build_inventory_records_a_sha256(synthetic_pdf):
    inventory = build_inventory(synthetic_pdf)
    assert len(inventory["source"]["sha256"]) == 64
    assert inventory["source"]["size_bytes"] > 0


def test_build_inventory_is_deterministic(synthetic_pdf):
    first = json.dumps(build_inventory(synthetic_pdf), sort_keys=True)
    second = json.dumps(build_inventory(synthetic_pdf), sort_keys=True)
    assert first == second


def test_every_page_has_a_type_and_a_reason(synthetic_pdf):
    inventory = build_inventory(synthetic_pdf)
    for page in inventory["pages"]:
        assert page["type"] in {
            "toc",
            "train_table",
            "line_table",
            "graphic",
            "legend",
            "other",
            "unknown",
        }
        assert page["reasons"], f"page {page['page']} has no reason"
        assert page["rule"] in range(1, 11)


def test_summarise_counts_add_up(synthetic_pdf):
    inventory = build_inventory(synthetic_pdf)
    summary = inventory["summary"]
    assert sum(summary["by_type"].values()) == 4
    assert sum(summary["by_section"].values()) == 4
    assert sum(summary["by_rule"].values()) == 4


def test_summarise_handles_an_empty_page_list():
    summary = summarise([])
    assert sum(summary["by_type"].values()) == 0
    assert summary["unknown_pages"] == []
    assert summary["train_numbers"]["union_distinct"] == 0


def test_write_json_creates_parent_directories(tmp_path):
    out = tmp_path / "nested" / "inventory.json"
    write_json({"schema_version": 1, "pages": []}, out)
    assert json.loads(out.read_text())["schema_version"] == 1


def test_main_writes_json_and_skips_report(synthetic_pdf, tmp_path):
    out = tmp_path / "inventory.json"
    code = main(["--pdf", str(synthetic_pdf), "--out", str(out), "--no-report"])
    assert code == 0
    assert json.loads(out.read_text())["source"]["page_count"] == 4


def test_main_fails_when_pdf_is_missing(tmp_path):
    code = main(["--pdf", str(tmp_path / "nope.pdf"), "--out", str(tmp_path / "o.json")])
    assert code == 2
