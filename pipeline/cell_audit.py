"""C2 — audit Keterangan cells for fragments, and Q2 — cell-token census.

Both are **report only**. A fragment is listed with its page, bbox, and
neighbouring rows so a human can see whether a wrapped multi-line cell was split
across row bands. Nothing is repaired unless a real parser defect is proven.

A "complete" Keterangan pattern (as observed):
  - ``= ka NNN (ka NNN //)``      cross-reference to another train
  - ``x ka NNN (ka NNN x)``       connection
  - ``// ka NNN``                  comment
  - ``jj =`` / ``(jj =)``          observed suffix form
  - ``Berh`` / ``Sb`` / ``Ls``     cell codes
Anything else is reported as a fragment.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_WORDS = Path("data/raw/words")
INVENTORY = Path("data/raw/inventory.json")

# A complete footnote/comment pattern.
# Printed marker tokens that may appear anywhere inside a Keterangan value.
MARKERS = ("jj", "x", "=", "//")

TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")

# Cell codes that legitimately appear in Datang / Berangkat.
CELL_CODES = {"LS", "BERH", "SB", "-", ""}

# Column headers and table furniture that land inside the x-window on pages whose
# layout differs (indexes, summaries, portrait tables).
HEADER_NOISE = {
    "DATANG",
    "BERANGKAT",
    "PELAYANAN",
    "LINTAS",
    "LINE",
    "COMMUTER",
    "KA",
    "KERETA",
    "API",
    "RELASI",
    "JENIS",
    "NAMA",
    "KELAS",
    "NOMOR",
}

# After marker tokens are removed, a complete value has one of these shapes.
# The inner parenthesised repeat must carry the SAME train number.
_AFTER_STRIP = [
    # = ka 46 (ka 46)      cross-reference with an explicit repeat
    re.compile(r"^=\s*ka\s*(\d+[A-Za-z]?)\s*\(\s*ka\s*\1\s*\)$", re.I),
    # x ka 361 (ka 361)    connection  — the space before "(" is optional in print
    re.compile(r"^x\s*ka\s*(\d+[A-Za-z]?)\s*\(\s*ka\s*\1\s*\)$", re.I),
    # ka 2703F (ka 2703F)  bare comment with a repeat
    re.compile(r"^ka\s*(\d+[A-Za-z]?)\s*\(\s*ka\s*\1\s*\)$", re.I),
    # ka 5014              a single bare reference
    re.compile(r"^ka\s*\d+[A-Za-z]?$", re.I),
    # (ka 348)             a bare parenthesised reference with no outer marker
    re.compile(r"^\(\s*ka\s*\d+[A-Za-z]?\s*\)$", re.I),
]


def _strip_markers(text: str) -> str:
    """Remove marker tokens (jj, x, =, //) so only the substance remains.

    Matching is case-insensitive because the document prints both ``jj`` and
    ``JJ``. The ``x`` marker may also be glued to a code (``ka 128x``), so it is
    stripped as a trailing/standalone token rather than only when isolated.
    """
    out = text
    for marker in ("jj", "//", "="):
        out = re.sub(re.escape(marker), " ", out, flags=re.I)
    # Standalone x, or x immediately after a train number / before ")".
    out = re.sub(r"(?<![A-Za-z])x(?![A-Za-z])", " ", out, flags=re.I)
    return " ".join(out.split())


def is_complete(text: str) -> bool:
    """True when the value is a complete footnote, not a fragment."""
    stripped = text.strip()
    if not stripped:
        return True
    # A cell may hold several complete patterns separated by commas.
    parts = [p.strip() for p in re.split(r",\s*(?=//|x |=|ka)", stripped) if p.strip()]
    for part in parts or [stripped]:
        normalised = _strip_markers(part)
        if not any(pattern.match(normalised) for pattern in _AFTER_STRIP):
            return False
    return True


def census(words_dir: Path = DEFAULT_WORDS, inventory_path: Path = INVENTORY) -> dict:
    """Every distinct non-time, non-code token in Datang/Berangkat, per section."""
    by_page = {}
    if inventory_path.exists():
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        by_page = {page["page"]: (page["section"], page["subtype"]) for page in inventory["pages"]}

    # token -> (section, subtype) -> {count, trains}
    tokens: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, dict[tuple[str, str], list[str]]] = defaultdict(lambda: defaultdict(list))

    for path in sorted(words_dir.glob("page_*.json")):
        page = int(path.stem.split("_")[1])
        section, subtype = by_page.get(page, ("unknown", "unknown"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows: dict[int, list] = {}
        for word in payload["words"]:
            rows.setdefault(round(word[1] / 3), []).append(word)
        for key in sorted(rows):
            line = sorted(rows[key], key=lambda w: w[0])
            # Datang / Berangkat columns sit at x in [260, 360) on A4 tables.
            for word in line:
                if not (255 <= word[0] < 360):
                    continue
                text = word[4].strip()
                if not text or TIME_RE.match(text) or text.upper() in CELL_CODES:
                    continue
                if text.upper() in HEADER_NOISE:
                    continue
                if text.isdigit():
                    continue
                tokens[text][(section, subtype)] += 1
                bucket = examples[text][(section, subtype)]
                if len(bucket) < 3:
                    bucket.append(f"p{page}")

    rows_out = []
    for token, per_section in sorted(tokens.items(), key=lambda kv: -sum(kv[1].values())):
        rows_out.append(
            {
                "token": token,
                "total": sum(per_section.values()),
                "by_section": {
                    f"{s}/{st}": {
                        "count": count,
                        "examples": examples[token][(s, st)],
                    }
                    for (s, st), count in per_section.most_common()
                },
            }
        )

    return {
        "note": "Census only. No code is mapped or interpreted.",
        "distinct_tokens": len(rows_out),
        "tokens": rows_out,
    }


def search_definitions(words_dir: Path = DEFAULT_WORDS) -> dict:
    """Search the whole PDF text for a definition of Berh / Sb."""
    patterns = {
        "berh": re.compile(r"\bBERH\b"),
        "sb": re.compile(r"\bSB\b"),
    }
    hits: dict[str, list[dict]] = {"berh": [], "sb": []}
    definition_words = re.compile(r"\b(BERARTI|ARTINYA|KETERANGAN|SINGKATAN|ADALAH|DEFINISI)\b")

    for path in sorted(words_dir.glob("page_*.json")):
        page = int(path.stem.split("_")[1])
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = " ".join(row[4] for row in payload["words"])
        upper = " ".join(text.upper().split())
        for key, pattern in patterns.items():
            if pattern.search(upper):
                contextual = bool(definition_words.search(upper))
                hits[key].append(
                    {
                        "page": page,
                        "has_definition_keyword": contextual,
                        "excerpt": upper[:160],
                    }
                )

    return {
        "note": (
            "Report only. 'has_definition_keyword' means the page also contains a "
            "word such as BERARTI/ARTINYA/SINGKATAN, which is where a definition "
            "would live."
        ),
        "berh_pages": len(hits["berh"]),
        "sb_pages": len(hits["sb"]),
        "berh_with_definition_keyword": [h for h in hits["berh"] if h["has_definition_keyword"]],
        "sb_with_definition_keyword": [h for h in hits["sb"] if h["has_definition_keyword"]],
        "berh_first_pages": hits["berh"][:15],
        "sb_first_pages": hits["sb"][:15],
    }


def check_fragments(trains: list[dict]) -> dict:
    """List every Keterangan value that does not match a complete pattern."""
    fragments = []
    for train in trains:
        stops = train["stops"]
        for index, stop in enumerate(stops):
            raw = (stop["note"]["raw"] or "").strip()
            if not raw or is_complete(raw):
                continue
            neighbours = []
            for offset in (-1, 1):
                position = index + offset
                if 0 <= position < len(stops):
                    adjacent = stops[position]
                    neighbours.append({"seq": adjacent["seq"], "station": adjacent["station_code"]})
            fragments.append(
                {
                    "train_no": train["train_no"],
                    "seq": stop["seq"],
                    "station": stop["station_code"],
                    "page": stop["note"]["page"],
                    "bbox": stop["note"]["bbox"],
                    "raw": raw,
                    "neighbours": neighbours,
                }
            )

    return {
        "note": (
            "Report only. 'fragments' are Keterangan values that do not match a "
            "complete footnote pattern; a wrapped cell split across two row bands "
            "is the most likely parser cause."
        ),
        "fragment_count": len(fragments),
        "distinct_fragments": dict(Counter(f["raw"] for f in fragments).most_common(30)),
        "fragments": fragments,
    }


def main() -> int:
    out = Path("data/review")
    out.mkdir(parents=True, exist_ok=True)

    census_report = census()
    (out / "cell_token_census.json").write_text(
        json.dumps(census_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"cell census: {census_report['distinct_tokens']} distinct tokens")
    for row in census_report["tokens"][:10]:
        print(f"  {row['token']!r}: {row['total']}")

    definitions = search_definitions()
    (out / "berh_sb_definition_search.json").write_text(
        json.dumps(definitions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"definition search: BERH on {definitions['berh_pages']} pages, "
        f"SB on {definitions['sb_pages']} pages"
    )
    print(
        f"  with a definition keyword: berh="
        f"{len(definitions['berh_with_definition_keyword'])}, "
        f"sb={len(definitions['sb_with_definition_keyword'])}"
    )

    parsed = Path("data/parsed/intercity_trips.json")
    if parsed.exists():
        trains = json.loads(parsed.read_text(encoding="utf-8"))["trains"]
        fragments = check_fragments(trains)
        (out / "keterangan_fragments.json").write_text(
            json.dumps(fragments, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"keterangan fragments: {fragments['fragment_count']}")
        for text, count in list(fragments["distinct_fragments"].items())[:8]:
            print(f"  {text!r}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
