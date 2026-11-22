"""Load human-authored station coordinate overrides (Q4).

`data/config/station_overrides.yaml` is written **only by the human**. This module
parses the small fixed subset of YAML it uses and validates every entry, so a typo
becomes a loud error instead of a silently wrong coordinate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT = Path("data/config/station_overrides.yaml")

# - code: "LR"
#   lat: -6.87
#   lon: 109.14
#   reason: "..."
_ENTRY_RE = re.compile(r"^\s*-\s+code:\s*\"?([A-Za-z0-9]+)\"?\s*$", re.MULTILINE)
_FIELD_RE = re.compile(
    r"^\s+(lat|lon|reason|evidence|decided_by|date|human_confirmed):\s*(.+?)\s*$",
    re.MULTILINE,
)

REQUIRED_FIELDS = ("lat", "lon", "reason", "evidence", "decided_by", "date")

# P1: provenance. A coordinate a human chose is not the same thing as a
# coordinate applied by a written rule with a passing gate, and the reports must
# not blur them.
PROVENANCE_HUMAN = "human_override"
PROVENANCE_RULE = "override_rule_approved"


def provenance_of(decided_by: str) -> str:
    """A `decided_by` starting with `rule:` means a rule was applied, not a person."""
    return PROVENANCE_RULE if decided_by.strip().lower().startswith("rule:") else PROVENANCE_HUMAN


@dataclass(frozen=True)
class Override:
    code: str
    lat: float
    lon: float
    reason: str
    evidence: str
    decided_by: str
    date: str
    human_confirmed: bool = False

    @property
    def provenance(self) -> str:
        return provenance_of(self.decided_by)


def _unquote(value: str) -> str:
    stripped = value.strip().rstrip(",").strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1]
    return stripped


def load(path: Path = DEFAULT) -> list[Override]:
    """Parse and validate the override file. Raises on any malformed entry."""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    if re.search(r"^overrides:\s*\[\s*\]\s*$", text, re.MULTILINE):
        return []

    # Split the "overrides:" block into entry chunks.
    if "overrides:" not in text:
        return []
    block = text.split("overrides:", 1)[1]
    # Drop trailing comments-only lines at the same indent as "overrides:".
    starts = [m.start() for m in _ENTRY_RE.finditer(block)]
    if not starts:
        return []

    overrides: list[Override] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(block)
        chunk = block[start:end]
        code_match = _ENTRY_RE.search(chunk)
        if not code_match:
            continue
        code = code_match.group(1)
        fields = {m.group(1): _unquote(m.group(2)) for m in _FIELD_RE.finditer(chunk)}

        missing = [f for f in REQUIRED_FIELDS if f not in fields]
        if missing:
            raise ValueError(f"override for {code} is missing field(s): {missing}")

        try:
            lat = float(fields["lat"])
            lon = float(fields["lon"])
        except ValueError as error:
            raise ValueError(f"override for {code} has a non-numeric lat/lon") from error

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"override for {code} is outside valid lat/lon ranges")

        overrides.append(
            Override(
                code=code,
                lat=lat,
                lon=lon,
                reason=fields["reason"],
                evidence=fields["evidence"],
                decided_by=fields["decided_by"],
                date=fields["date"],
                human_confirmed=fields.get("human_confirmed", "").lower() in ("true", "yes", "1"),
            )
        )

    codes = [o.code for o in overrides]
    duplicates = {code for code in codes if codes.count(code) > 1}
    if duplicates:
        raise ValueError(f"duplicate override codes: {sorted(duplicates)}")

    return overrides


def apply_to(overrides: list[Override], matched: dict[str, dict]) -> dict[str, dict]:
    """Return the coordinate map with overrides taking precedence.

    Every overridden entry gets ``source='override'``, ``confidence='high'`` and
    ``coord_status='override'``, plus ``coord_provenance`` which distinguishes a
    human choice from a rule-approved one (P1).
    """
    result = {code: {**entry, "coord_status": "accepted"} for code, entry in matched.items()}
    for override in overrides:
        result[override.code] = {
            "code": override.code,
            "name": result.get(override.code, {}).get("name", override.code),
            "lat": override.lat,
            "lon": override.lon,
            "source": "override",
            "source_id": f"{override.decided_by}:{override.date}",
            "coord_provenance": override.provenance,
            "human_confirmed": override.human_confirmed,
            "match_method": "human",
            "confidence": "high",
            "retrieved": override.date,
            "in_java_bbox": True,
            "coord_status": "override",
            "reason": override.reason,
            "evidence": override.evidence,
        }
    return result
