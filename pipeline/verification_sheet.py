"""T1: the human verification sheet.

Builds a self-contained HTML page: one section per selected train, with the
rendered PDF page image(s) beside the parsed table, so a human can compare them
without a PDF reader. Every row defaults to OK; clicking a row marks it wrong and
opens a note box. A button downloads ``verification_result.json``.

The selection is stratified and deterministic (documented seed). The strata are
the hard cases: fakultatif, Berh/Sb markers, untimed Ls rows, midnight crossings,
midnight-straddling stops, multi-page tables, footnotes, non-zero seconds,
complete_estimated, plus the longest and a short trip.

Images go to ``data/review/img/`` (gitignored).

Usage:
    python -m pipeline.verification_sheet
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from pipeline.review_html import esc, render_page_image

DB = Path("data/gapeka.db")
PDF = Path("data/input/GAPEKA_2026.pdf")
REVIEW = Path("data/review")
OUT = REVIEW / "verification_sheet.html"
SELECTION_OUT = REVIEW / "verification_selection.json"

SEED = 20261201
TARGET = 20

# Already compared by a human; excluded so the 20 are all new evidence.
EXCLUDE_TRAINS = {"249", "250", "251", "252", "259F", "260F"}

# The human's required minimum per stratum.
REQUIREMENTS = {
    "book1": 10,
    "book2": 6,
    "fakultatif": 3,
    "marker": 2,
    "untimed_ls": 2,
    "midnight": 2,
    "midnight_straddle": 1,
    "multipage": 3,
    "footnote": 3,
    "seconds": 3,
    "complete_estimated": 2,
}


def _features(connection: sqlite3.Connection) -> list[dict]:
    """Per-trip facts used for stratification, from the database."""
    trips = connection.execute(
        "SELECT t.trip_id, t.train_no, t.book, t.service_class, t.source_pages,"
        " t.relation, t.has_untimed_markers, g.status, tr.name"
        " FROM trips t"
        " JOIN trip_geometry_status g ON g.trip_id = t.trip_id"
        " LEFT JOIN trains tr ON tr.train_no = t.train_no"
        " WHERE g.status IN ('complete', 'complete_estimated')"
        " ORDER BY t.trip_id"
    ).fetchall()

    rows: list[dict] = []
    for (
        trip_id,
        train_no,
        book,
        service_class,
        source_pages,
        relation,
        has_untimed,
        status,
        name,
    ) in trips:
        if train_no in EXCLUDE_TRAINS:
            continue

        stops = connection.execute(
            "SELECT station_code, arrive, depart, day_offset, arrive_day_offset,"
            " depart_day_offset, stop_type, time_source, keterangan_raw, speed_raw"
            " FROM stop_times WHERE trip_id = ? ORDER BY seq",
            (trip_id,),
        ).fetchall()

        pages = json.loads(source_pages) if source_pages else []
        marker = any(row[7] == "marker" for row in stops)
        # An "untimed Ls row": a pass row with no printed time.
        untimed_ls = any(
            row[6] == "pass" and row[7] in ("not_printed", "marker", "empty") for row in stops
        )
        midnight = any((row[3] or 0) >= 1 for row in stops)
        straddle = any(
            row[4] is not None and row[5] is not None and row[4] != row[5] for row in stops
        )
        footnote = any((row[8] or "").strip() for row in stops)
        seconds = any(
            (value or "").endswith((":01", ":02", ":03", ":04", ":05", ":06", ":07", ":08", ":09"))
            or (value or "")[-2:] not in ("00", "")
            for value in (row[1] for row in stops)
        ) or any((row[2] or "")[-2:] not in ("00", "") for row in stops if row[2])

        rows.append(
            {
                "trip_id": trip_id,
                "train_no": train_no,
                "book": book,
                "service_class": service_class,
                "name": name or "",
                "relation": relation or "",
                "status": status,
                "pages": pages,
                "stops": len(stops),
                "marker": marker,
                "untimed_ls": untimed_ls,
                "midnight": midnight,
                "midnight_straddle": straddle,
                "multipage": len(pages) > 1,
                "footnote": footnote,
                "seconds": seconds,
                "has_untimed_markers": bool(has_untimed),
                "complete_estimated": status == "complete_estimated",
            }
        )
    return rows


def _lengths(connection: sqlite3.Connection) -> dict[str, float]:
    return {
        row[0]: row[1] or 0.0
        for row in connection.execute("SELECT trip_id, total_length_m FROM trip_geometry_status")
    }


def select() -> dict:
    """Deterministic stratified selection of 20 trains."""
    if not DB.exists():
        raise FileNotFoundError(DB)
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        candidates = _features(connection)
        lengths = _lengths(connection)
    finally:
        connection.close()

    if not candidates:
        raise ValueError("no candidate trips")

    longest = max(candidates, key=lambda row: lengths.get(row["trip_id"], 0.0))
    shortest = min(candidates, key=lambda row: lengths.get(row["trip_id"], 0.0))

    def strata_of(row: dict) -> set[str]:
        keys = {"book1" if row["book"] == 1 else "book2"}
        if row["service_class"] == "fakultatif":
            keys.add("fakultatif")
        for key in (
            "marker",
            "untimed_ls",
            "midnight",
            "midnight_straddle",
            "multipage",
            "footnote",
            "seconds",
            "complete_estimated",
        ):
            if row[key]:
                keys.add(key)
        return keys

    # Deterministic tie-break: shuffle once with the documented seed.
    order = list(candidates)
    random.Random(SEED).shuffle(order)
    rank = {row["trip_id"]: index for index, row in enumerate(order)}

    chosen: list[dict] = []
    covered: dict[str, int] = {key: 0 for key in REQUIREMENTS}

    def take(row: dict, reason: str) -> None:
        if row["trip_id"] in {item["trip_id"] for item in chosen}:
            return
        chosen.append({**row, "reason": reason})
        for key in strata_of(row):
            covered[key] = covered.get(key, 0) + 1

    # 1. The two explicitly named trips.
    take(longest, "longest trip by routed length")
    if shortest["trip_id"] != longest["trip_id"]:
        take(shortest, "shortest trip by routed length")

    # 2. Greedy: each step takes the train that satisfies the most unmet strata.
    while len(chosen) < TARGET:
        best = None
        best_score = -1
        for row in candidates:
            if row["trip_id"] in {item["trip_id"] for item in chosen}:
                continue
            score = 0
            for key in strata_of(row):
                need = REQUIREMENTS.get(key, 0) - covered.get(key, 0)
                if need > 0:
                    score += 1
            # Prefer a train that adds a NEW page range, so the sheet is diverse.
            if score > best_score or (
                score == best_score
                and best is not None
                and rank[row["trip_id"]] < rank[best["trip_id"]]
            ):
                best = row
                best_score = score
        if best is None:
            break
        met = sorted(
            key for key in strata_of(best) if REQUIREMENTS.get(key, 0) > covered.get(key, 0)
        )
        reason = "fills " + ", ".join(met) if met else "diversity fill"
        take(best, reason)

    return {
        "seed": SEED,
        "requirements": REQUIREMENTS,
        "strata": covered,
        "trains": chosen,
        "longest_trip_id": longest["trip_id"],
        "shortest_trip_id": shortest["trip_id"],
    }


def _stop_rows(connection: sqlite3.Connection, trip_id: str) -> list[dict]:
    rows = connection.execute(
        "SELECT seq, station_code, speed_raw, arrive, depart, raw_arrive, raw_depart,"
        " keterangan_raw, stop_type, day_offset, arrive_day_offset, depart_day_offset,"
        " time_source, source_page"
        " FROM stop_times WHERE trip_id = ? ORDER BY seq",
        (trip_id,),
    ).fetchall()
    stations = {
        row[0]: row[1] for row in connection.execute("SELECT code, official_name FROM stations")
    }
    out = []
    for row in rows:
        out.append(
            {
                "seq": row[0],
                "code": row[1],
                "station": stations.get(row[1]) or row[1],
                "speed": row[2] or "",
                "arrive": row[3] or "",
                "depart": row[4] or "",
                "raw_arrive": row[5] or "",
                "raw_depart": row[6] or "",
                "keterangan": row[7] or "",
                "type": row[8],
                "day_offset": row[9],
                "arrive_day_offset": row[10],
                "depart_day_offset": row[11],
                "time_source": row[12],
                "page": row[13],
            }
        )
    return out


def script_json(payload: object) -> str:
    """JSON that is safe to embed inside a <script> block.

    HTML entities are NOT decoded inside <script>, so ``html.escape`` corrupts the
    JSON: ``"`` becomes ``&quot;``, the script fails to parse ("Unexpected token
    '&'") and every handler silently disappears — which is why the download
    button did nothing.

    Instead, escape only the sequences that could terminate or confuse the block.
    ``\\u003c`` is valid JSON *and* valid JavaScript.
    """
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build(selection: dict) -> str:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sections = []
        for index, train in enumerate(selection["trains"], start=1):
            stops = _stop_rows(connection, train["trip_id"])
            images = []
            for page in train["pages"]:
                image = render_page_image(PDF, page, REVIEW)
                if image is not None:
                    images.append(
                        f'<figure><img src="{esc(image.relative_to(REVIEW))}"'
                        f' alt="Halaman PDF {page} untuk KA {esc(train["train_no"])}"'
                        f' loading="lazy" width="595" height="842">'
                        f"<figcaption>PDF halaman {page}</figcaption></figure>"
                    )
            rows = []
            for stop in stops:
                rows.append(
                    f'<tr data-seq="{stop["seq"]}">'
                    f"<td>{stop['seq']}</td>"
                    f"<td>{esc(stop['station'])} <small>({esc(stop['code'])})</small></td>"
                    f"<td>{esc(stop['speed'])}</td>"
                    f"<td>{esc(stop['arrive'])}</td>"
                    f"<td>{esc(stop['depart'])}</td>"
                    f"<td>{esc(stop['keterangan'])}</td>"
                    f"<td>{esc(stop['type'])}</td>"
                    f"<td>{stop['day_offset']}/{stop['arrive_day_offset']}"
                    f"/{stop['depart_day_offset']}</td>"
                    f"<td>{esc(stop['time_source'])}</td>"
                    f'<td><input class="row-note" type="text" disabled'
                    f' aria-label="Catatan untuk baris {stop["seq"]},'
                    f' stasiun {esc(stop["station"])}"'
                    f' placeholder="apa yang salah?"></td>'
                    "</tr>"
                )
            sections.append(
                f"""
<section class="train" data-trip="{esc(train["trip_id"])}" data-train="{esc(train["train_no"])}">
  <header>
    <h2>{index}. KA {esc(train["train_no"])} — {esc(train["name"]) or "(tanpa nama)"}</h2>
    <p class="meta">
      {esc(train["relation"])} · buku {train["book"]} · {esc(train["service_class"])} ·
      {esc(train["status"])} · {train["stops"]} baris · halaman
      {esc(", ".join(str(p) for p in train["pages"]))}
    </p>
    <p class="reason">Alasan dipilih: {esc(train["reason"])}</p>
    <p class="verdict">
      <label><input type="radio" name="verdict-{index}" value="ok" checked>
        Semua baris cocok</label>
      <label><input type="radio" name="verdict-{index}" value="errors">
        Ada kesalahan</label>
      <span class="count" id="count-{index}">0 baris ditandai</span>
    </p>
  </header>
  <div class="body">
    <div class="pages">{"".join(images) or "<p>Gambar halaman tidak tersedia.</p>"}</div>
    <div class="table-wrap">
      <p class="hint">Klik satu baris untuk menandainya salah. Baris hijau = cocok.</p>
      <table>
        <thead><tr>
          <th>#</th><th>Stasiun</th><th>Kecepatan</th><th>Datang</th>
          <th>Berangkat</th><th>Keterangan</th><th>type</th>
          <th>day/arr/dep</th><th>time_source</th><th>Catatan</th>
        </tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </div>
</section>"""
            )
    finally:
        connection.close()

    return (
        _TEMPLATE.replace("__SECTIONS__", "\n".join(sections))
        .replace("__SELECTION__", script_json(selection["trains"]))
        .replace("__SEED__", script_json(selection.get("seed")))
    )


_TEMPLATE = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lembar verifikasi 20 KA — Gapeka 2026</title>
<style>
 :root{color-scheme:light}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
   font-size:14px;color:#0f172a}
 header.top{position:sticky;top:0;z-index:5;background:#fff;
   border-bottom:2px solid #0f172a;padding:10px 14px}
 header.top h1{margin:0;font-size:17px}
 header.top p{margin:4px 0 0;font-size:12px;color:#5b6472}
 header.top .actions{margin-top:8px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 button{min-height:44px;padding:0 16px;border-radius:8px;border:1px solid #0f172a;
   background:#0f172a;color:#fff;font:inherit;font-weight:600;cursor:pointer}
 button.secondary{background:#fff;color:#0f172a}
 .train{border-bottom:3px solid #d7dce3;padding:14px}
 .train h2{margin:0 0 4px;font-size:16px}
 .meta,.reason{font-size:12px;color:#5b6472;margin:2px 0}
 .verdict{display:flex;gap:16px;align-items:center;margin:8px 0;flex-wrap:wrap;font-size:13px}
 .verdict label{display:flex;gap:6px;align-items:center;min-height:32px;cursor:pointer}
 .count{font-weight:600;color:#b00020}
 .body{display:grid;grid-template-columns:1fr;gap:14px}
 @media(min-width:1100px){.body{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
 .pages img{width:100%;height:auto;border:1px solid #d7dce3;display:block}
 figure{margin:0 0 10px}
 figcaption{font-size:11px;color:#5b6472}
 .table-wrap{overflow:auto}
 table{border-collapse:collapse;width:100%;font-size:12px}
 th,td{border:1px solid #d7dce3;padding:3px 6px;text-align:left;vertical-align:top}
 th{background:#f4f6f9;position:sticky;top:0}
 tbody tr{cursor:pointer}
 tbody tr:hover{background:#eef4fd}
 tbody tr.wrong{background:#ffe9ec}
 tbody tr.wrong td{text-decoration:line-through}
 .row-note{width:100%;min-width:12rem;min-height:32px;font:inherit;font-size:12px;
   padding:2px 6px;border:1px solid #d7dce3;border-radius:4px;background:#fff}
 .row-note:disabled{background:#f4f6f9;border-color:transparent;cursor:not-allowed}
 tbody tr.wrong .row-note:disabled{background:#fff}
 .hint{font-size:12px;color:#5b6472;margin:0 0 6px}
 .summary{background:#f4f6f9;border:1px solid #d7dce3;border-radius:8px;
   padding:10px;margin:10px 0;font-size:13px}
</style>
</head>
<body>
<header class="top">
  <h1>Lembar verifikasi 20 KA — Gapeka 2026</h1>
  <p>Bandingkan gambar halaman PDF di kiri dengan tabel hasil parsing di kanan.
     Semua baris dianggap <b>cocok</b>; klik baris yang salah. Selesai, unduh hasilnya.</p>
  <div class="actions">
    <button id="download">Unduh verification_result.json</button>
    <button class="secondary" id="reset">Atur ulang</button>
    <span id="summary" class="summary" style="margin:0">Belum ada baris ditandai.</span>
  </div>
</header>
<main id="trains">
__SECTIONS__
</main>
<script>
const SELECTION = __SELECTION__;
const SELECTION_SEED = __SEED__;
const wrong = {};   // tripId -> [{seq, note}]

function trainSections(){ return [...document.querySelectorAll('section.train')]; }

function updateCount(section){
  const trip = section.dataset.trip;
  const rows = (wrong[trip] || []);
  const badge = section.querySelector('.count');
  badge.textContent = rows.length + ' baris ditandai';
  const verdictErrors = section.querySelector('input[value="errors"]');
  const verdictOk = section.querySelector('input[value="ok"]');
  if (rows.length > 0) verdictErrors.checked = true;
  else verdictOk.checked = true;
}

function updateSummary(){
  const total = Object.values(wrong).reduce((n, rows) => n + rows.length, 0);
  const trains = Object.keys(wrong).filter(k => wrong[k].length > 0).length;
  document.getElementById('summary').textContent =
    total === 0 ? 'Belum ada baris ditandai.' :
    trains + ' KA dengan kesalahan, ' + total + ' baris ditandai.';
}

trainSections().forEach(section => {
  const trip = section.dataset.trip;
  const rows = [...section.querySelectorAll('tbody tr')];
  rows.forEach((row, index) => {
    row.addEventListener('click', () => {
      row.classList.toggle('wrong');
      const seq = Number(row.cells[0].textContent);
      wrong[trip] = (wrong[trip] || []).filter(r => r.seq !== seq);
      const input = row.querySelector('.row-note');
      if (input) {
        input.disabled = !row.classList.contains('wrong');
        if (!row.classList.contains('wrong')) input.value = '';
      }
      if (row.classList.contains('wrong')) {
        wrong[trip].push({ seq, note: input ? input.value : '' });
      }
      updateCount(section); updateSummary();
    });
  });
});

document.getElementById('reset').addEventListener('click', () => {
  if (!confirm('Atur ulang semua tanda?')) return;
  Object.keys(wrong).forEach(k => delete wrong[k]);
  document.querySelectorAll('tbody tr.wrong').forEach(r => r.classList.remove('wrong'));
  document.querySelectorAll('.row-note')
    .forEach(i => { i.value=''; i.disabled = true; });
  trainSections().forEach(s => { updateCount(s); });
  updateSummary();
});

document.getElementById('download').addEventListener('click', () => {
  const payload = {
    note: 'Hasil verifikasi manual. Diunggah ke pipeline/import_verifications.py.',
    date: new Date().toISOString().slice(0, 10),
    verifier: 'human',
    method: 'visual comparison of PDF page images against the parsed table',
    selection_seed: SELECTION_SEED,
    trains: SELECTION.map(t => ({
      trip_id: t.trip_id,
      train_no: t.train_no,
      book: t.book,
      verdict: (wrong[t.trip_id] || []).length ? 'has_errors' : 'all_rows_match',
      wrong_rows: (wrong[t.trip_id] || []).map((entry) => {
        const row = document.querySelector(
          `section[data-trip="${t.trip_id}"] tbody tr[data-seq="${entry.seq}"]`,
        );
        const input = row ? row.querySelector('.row-note') : null;
        return { seq: entry.seq, note: input ? input.value.trim() : entry.note };
      }),
      pages: t.pages,
    })),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'verification_result.json';
  link.click();
  URL.revokeObjectURL(url);
});
</script>
</body>
</html>
"""


def main() -> int:
    selection = select()
    SELECTION_OUT.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    html = build(selection)
    OUT.write_text(html, encoding="utf-8")

    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} kB)")
    print(f"wrote {SELECTION_OUT}")
    print(f"seed {selection['seed']}, {len(selection['trains'])} trains")
    for key, need in selection["requirements"].items():
        got = selection["strata"].get(key, 0)
        flag = "OK " if got >= need else "MISSING"
        print(f"  {flag} {key}: {got} (need {need})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
