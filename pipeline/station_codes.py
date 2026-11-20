"""Station-code extraction and V3b: code<->name consistency across the whole PDF.

V3 (per trip) is circular: the stations table is built from the same parsed rows
it validates. It is therefore labelled ``V3-circular: informational``.

V3b is different: it is an **extraction-only** sweep over all 1,887 raw pages.
It never parses a table, so it cannot be circular with the table parser. It
requires that every station code maps to exactly one printed name and every name
to exactly one code. Conflicts and near-duplicates are reported, never resolved.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# "Semarang Poncol (SMC)" -> name, code. The name may contain dots and hyphens.
PAIR_RE = re.compile(r"([A-Za-z][A-Za-z.\-']*(?:\s+[A-Za-z.\-']+)*)\s*\(([A-Z]{2,5})\)")

# A station-table row, as printed: seq, name (CODE), then speed/time/Ls columns.
# Requiring this shape keeps depots, legends, and capacity diagrams out of the
# station-code sweep: they also print parenthesised codes but are not stations.
STATION_ROW_RE = re.compile(
    r"^\s*(\d{1,3})\s*"  # sequence number
    r"([A-Za-z][A-Za-z.\-']*(?:\s+[A-Za-z.\-']+)*)\s*"  # station name
    r"\(([A-Z]{2,5})\)\s*"  # (CODE)
    r"(?:\d{1,3}|-)?\s*"  # speed
    r"(?:Ls|Ls\.|\d{2}:\d{2}:\d{2}|-)"  # a time, Ls, or dash must follow
)

# Words that are never a station name on their own; they appear in headers,
# footnotes, and legend lines that also contain parenthesised codes.
STOPWORDS = {
    "KA",
    "KRL",
    "LINTAS",
    "RELASI",
    "UNTUK",
    "DAN",
    "MAKSIMUM",
    "KECEPATAN",
    "KETERANGAN",
    "STASIUN",
    "PERHENTIAN",
    "DATANG",
    "BERANGKAT",
}

DEFAULT_WORDS = Path("data/raw/words")


@dataclass
class CodeNameIndex:
    """All observed (code, name) pairs and their conflicts."""

    code_to_names: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    name_to_codes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    pages_scanning: int = 0
    pairs_found: int = 0

    def as_dict(self) -> dict:
        code_conflicts = {
            code: sorted(names)
            for code, names in sorted(self.code_to_names.items())
            if len(names) > 1
        }
        name_conflicts = {
            name: sorted(codes)
            for name, codes in sorted(self.name_to_codes.items())
            if len(codes) > 1
        }
        return {
            "pages_scanned": self.pages_scanning,
            "distinct_codes": len(self.code_to_names),
            "distinct_names": len(self.name_to_codes),
            "pairs_found": self.pairs_found,
            "code_to_multiple_names": code_conflicts,
            "name_to_multiple_codes": name_conflicts,
            "code_conflict_count": len(code_conflicts),
            "name_conflict_count": len(name_conflicts),
        }


def _normalise_name(text: str) -> str:
    return " ".join(text.upper().split())


def scan_payload(payload: dict, index: CodeNameIndex) -> None:
    """Extract (name, code) pairs from station rows of one raw page payload."""
    words = payload.get("words", [])
    if not words:
        return
    # Rebuild text lines from word coordinates so a wrapped row is not joined
    # across two unrelated columns.
    rows: dict[int, list] = {}
    for row in words:
        rows.setdefault(round(row[1] / 3), []).append(row)
    for key in sorted(rows):
        line = " ".join(row[4] for row in sorted(rows[key], key=lambda r: r[0]))
        if "(" not in line:
            continue
        match = STATION_ROW_RE.match(line)
        if not match:
            continue
        name, code = match.group(2), match.group(3)
        cleaned = _normalise_name(name)
        if not cleaned or cleaned in STOPWORDS or len(cleaned) < 2:
            continue
        index.code_to_names[code].add(cleaned)
        index.name_to_codes[cleaned].add(code)
        index.pairs_found += 1


def scan_words_dir(words_dir: Path = DEFAULT_WORDS) -> CodeNameIndex:
    """Scan every raw page. Extraction only: no table parsing, no inference."""
    index = CodeNameIndex()
    for path in sorted(words_dir.glob("page_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scan_payload(payload, index)
        index.pages_scanning += 1
    return index


def near_duplicates(names: set[str], threshold: int = 1) -> list[tuple[str, str]]:
    """Pairs of names that are one edit apart, or where one is a prefix of the other.

    Reported only; never merged. A human decides whether two spellings are the
    same station. Edit distance 2 produces too much noise on short Indonesian
    station names (``BATANG``/``LAWANG``/``MALANG``), so the default is 1.
    """
    ordered = sorted(names)
    pairs: list[tuple[str, str]] = []
    for i, left in enumerate(ordered):
        for right in ordered[i + 1 :]:
            if abs(len(left) - len(right)) > threshold:
                continue
            if _edit_distance(left, right) <= threshold:
                pairs.append((left, right))
    return pairs


def prefix_pairs(names: set[str], min_length: int = 6) -> list[tuple[str, str]]:
    """A name that is a prefix of another is a likely truncation, not a typo."""
    ordered = sorted(names)
    pairs: list[tuple[str, str]] = []
    for left in ordered:
        for right in ordered:
            if left == right or len(left) < min_length:
                continue
            if right.startswith(left):
                pairs.append((left, right))
    return pairs


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ch_a != ch_b),
                )
            )
        previous = current
    return previous[-1]


def v3b_report(index: CodeNameIndex) -> dict:
    """Build the V3b validation record."""
    payload = index.as_dict()
    payload["rule"] = "V3b"
    payload["description"] = (
        "every station code maps to exactly one printed name, and every name to "
        "exactly one code (extraction-only sweep over all raw pages)"
    )
    payload["circular"] = False
    payload["note"] = (
        "Conflicts are listed, never resolved. Pass/fail is informational: the "
        "document may genuinely print two spellings for one code."
    )
    names = set(index.name_to_codes)
    duplicates = near_duplicates(names)
    prefixes = prefix_pairs(names)
    payload["near_duplicate_names"] = [
        {
            "a": a,
            "b": b,
            "codes_a": sorted(index.name_to_codes[a]),
            "codes_b": sorted(index.name_to_codes[b]),
        }
        for a, b in duplicates
    ]
    payload["near_duplicate_count"] = len(duplicates)
    payload["prefix_pairs"] = [
        {
            "shorter": a,
            "longer": b,
            "codes_shorter": sorted(index.name_to_codes[a]),
            "codes_longer": sorted(index.name_to_codes[b]),
        }
        for a, b in prefixes
    ]
    payload["prefix_pair_count"] = len(prefixes)
    return payload
