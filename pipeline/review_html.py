"""HTML review artefacts for human verification.

Two invariants the generator guarantees, both enforced by tests:

1. every ``<tr>`` in a data table has exactly as many ``<td>``/``<th>`` cells as
   the table's header row;
2. every cell shows the raw token, so a human compares like-for-like with the PDF.

Page images are rendered next to their tables so the comparison needs no PDF
reader. Images live in ``data/review/img/`` and are gitignored.
"""

from __future__ import annotations

import html
from pathlib import Path

import pymupdf

IMG_DIRNAME = "img"
IMAGE_DPI = 110

STOP_TABLE_HEADERS = [
    "#",
    "Station",
    "Speed",
    "Datang",
    "Berangkat",
    "Keterangan",
    "type",
    "day",
    "flags",
]


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_page_image(pdf: Path, page: int, out_dir: Path) -> Path | None:
    """Render one PDF page to ``out_dir/img/page_XXXX.png``. Returns None on failure."""
    image_dir = out_dir / IMG_DIRNAME
    image_dir.mkdir(parents=True, exist_ok=True)
    target = image_dir / f"page_{page:04d}.png"
    if target.exists():
        return target
    try:
        doc = pymupdf.open(pdf)
        try:
            pixmap = doc[page - 1].get_pixmap(dpi=IMAGE_DPI)
        finally:
            doc.close()
        pixmap.save(target)
    except Exception:  # noqa: BLE001 - a missing image must not break the report
        return None
    return target


def cell_html(stop: dict, key: str) -> str:
    """Render one cell as a ``<td>``, always showing the raw token."""
    cell = stop[key]
    raw = cell.get("raw") or ""
    value = cell.get("value")
    if value is not None:
        inner = esc(value)
        if raw and raw != value:
            inner += f' <small class="raw">({esc(raw)})</small>'
    elif raw:
        # Unparsed or explicitly absent: show the printed token verbatim.
        inner = f"<em>{esc(raw)}</em>"
    else:
        inner = '<em class="empty">∅</em>'
    return f"<td>{inner}</td>"


def flags_text(stop: dict) -> str:
    parts = []
    if stop["needs_review"]:
        parts.append("needs_review: " + "; ".join(stop["needs_review"]))
    if stop["info"]:
        parts.append("info: " + "; ".join(stop["info"]))
    return " | ".join(parts)


def stop_table_html(train: dict) -> list[str]:
    """Render one train's stop table, guaranteeing one ``<td>`` per header cell."""
    lines = ['<table class="stops">']
    lines.append("<tr>" + "".join(f"<th>{esc(h)}</th>" for h in STOP_TABLE_HEADERS) + "</tr>")
    for stop in train["stops"]:
        css = ' class="flag"' if stop["needs_review"] else ""
        cells = [
            f"<td>{esc(stop['seq'])}</td>",
            f"<td>{esc(stop['station_name'])} ({esc(stop['station_code'] or '?')})</td>",
            cell_html(stop, "speed"),
            cell_html(stop, "arrive"),
            cell_html(stop, "depart"),
            cell_html(stop, "note"),
            f"<td>{esc(stop['stop_type'])}</td>",
            f"<td>{esc(stop['day_offset'])}</td>",
            f"<td>{esc(flags_text(stop))}</td>",
        ]
        lines.append(f"<tr{css}>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return lines


def rule_table_html(reports: list[dict]) -> list[str]:
    headers = ["Rule", "Description", "Checked", "Violations", "Result"]
    lines = ["<table>", "<tr>" + "".join(f"<th>{esc(h)}</th>" for h in headers) + "</tr>"]
    for report in reports:
        label = report.get("label", report["rule"])
        status = "PASS" if report["passed"] else "FAIL"
        css = ' class="ok"' if report["passed"] else ' class="flag"'
        cells = [
            f"<td>{esc(label)}</td>",
            f"<td>{esc(report['description'])}</td>",
            f"<td>{esc(report['checked'])}</td>",
            f"<td>{esc(report['violation_count'])}</td>",
            f"<td>{esc(status)}</td>",
        ]
        lines.append(f"<tr{css}>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return lines


def train_section_html(train: dict, images: dict[int, str]) -> list[str]:
    pages = sorted({s["provenance"]["page"] for s in train["stops"]})
    quarantined = bool(train.get("quarantined"))
    banner = (
        [
            '<p class="quarantine">QUARANTINED — this train did NOT enter '
            "data/validated. Reasons: "
            + esc("; ".join(train.get("quarantine_reasons") or ["unspecified"]))
            + "</p>"
        ]
        if quarantined
        else []
    )
    lines = [
        f"<h2>KA {esc(train['train_no'] or '?')} — {esc(train['name'] or 'unknown')} "
        f"<small>({esc(train['origin'])}–{esc(train['destination'])}) · "
        f"{esc(train['completeness'])}</small></h2>",
        '<p class="meta">PDF page(s): '
        + ", ".join(f'<a href="{esc(images[p])}">{p}</a>' if p in images else str(p) for p in pages)
        + f" · column source: {esc(train['column_source'])}</p>",
    ]
    lines.extend(banner)
    badges = []
    if train["info"]:
        badges.append(f'<span class="info">info: {esc("; ".join(train["info"]))}</span>')
    if train["needs_review"]:
        badges.append(
            f'<span class="flag">needs_review: {esc("; ".join(train["needs_review"]))}</span>'
        )
    if badges:
        lines.append("<p>" + " ".join(badges) + "</p>")

    for page in pages:
        if page in images:
            lines.append(
                f'<figure><a href="{esc(images[page])}">'
                f'<img src="{esc(images[page])}" alt="PDF page {page}"></a>'
                f"<figcaption>PDF page {page}</figcaption></figure>"
            )
    lines.extend(stop_table_html(train))
    return lines


CSS = """
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2rem; max-width: 1200px; }
  table { border-collapse: collapse; margin: 1rem 0 2rem; font-size: 13px; }
  th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; vertical-align: top; }
  th { background: #f0f0f0; }
  tr.flag td { background: #ffe0e0; }
  p.quarantine { background: #b00020; color: #fff; padding: 8px 12px; font-weight: 600; }
  tr.ok td { background: #e0ffe0; }
  .info { background: #fff6d0; padding: 2px 4px; }
  .flag { padding: 2px 4px; }
  h2 { margin-top: 2.5rem; border-top: 2px solid #ddd; padding-top: 1rem; }
  small { color: #666; font-weight: normal; }
  small.raw { color: #999; }
  em.empty { color: #bbb; font-style: normal; }
  figure { margin: 1rem 0; }
  figure img { max-width: 100%; border: 1px solid #999; }
  figcaption { color: #666; font-size: 12px; }
  p.meta { color: #555; font-size: 13px; }
"""


def render_review_html(
    title: str,
    trains: list[dict],
    reports: list[dict],
    footnotes: list[dict],
    images: dict[int, str] | None = None,
    notes: str = "",
    status_line: str = "DRAFT, generated by the parser. Not verified by a human.",
) -> str:
    images = images or {}
    body: list[str] = [
        f"<h1>{esc(title)}</h1>",
        f"<p><strong>Status: {esc(status_line)}</strong></p>",
    ]
    if notes:
        body.append(notes)

    body.append("<h2>Validator results</h2>")
    body.extend(rule_table_html(reports))

    body.append("<h2>Footnote patterns (verbatim, not interpreted)</h2>")
    if footnotes:
        items = "".join(
            f"<li><code>{esc(f['text'])}</code> ×{esc(f['count'])}</li>" for f in footnotes
        )
        body.append(f"<ul>{items}</ul>")
    else:
        body.append("<p>None found.</p>")

    for train in trains:
        body.extend(train_section_html(train, images))

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )
