"""Human snap pins (Q1a).

A station can sit between two adjacent tracks. ``snap`` takes the geometrically
nearest edge, which can be a stub that forces a long detour. A pin says "this
station is on THIS way", and the snap then uses the nearest point on that way.

The pin is a human decision, recorded in ``data/config/snap_pins.yaml``. The
pipeline never writes it.

A pin is only honoured when the station is within ``snap_accept_m`` of the pinned
way; otherwise the pin is reported as unusable and the normal snap is used.

Usage:
    python -m pipeline.snap_pins
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("data/config/snap_pins.yaml")


@dataclass(frozen=True)
class Pin:
    station: str
    way_id: int
    reason: str
    evidence: str
    decided_by: str
    date: str


def _unquote(value: str) -> str:
    return value.strip().rstrip(",").strip().strip('"').strip("'")


def load(path: Path = DEFAULT_PATH) -> list[Pin]:
    """Parse the pin file. A malformed entry is a loud error, never a guess."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if "pins:" not in text:
        return []
    block = text.split("pins:", 1)[1]

    pins: list[Pin] = []
    current: dict[str, str] | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- station:"):
            current = {"station": _unquote(stripped.split(":", 1)[1])}
            pins.append(current)  # type: ignore[arg-type]
            continue
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = _unquote(value)

    out: list[Pin] = []
    for entry in pins:
        if "station" not in entry or "way_id" not in entry:
            continue
        try:
            way_id = int(entry["way_id"])
        except ValueError as error:
            raise ValueError(
                f"snap pin for {entry.get('station')} has a non-numeric way_id"
            ) from error
        out.append(
            Pin(
                station=entry["station"],
                way_id=way_id,
                reason=entry.get("reason", ""),
                evidence=entry.get("evidence", ""),
                decided_by=entry.get("decided_by", ""),
                date=entry.get("date", ""),
            )
        )

    stations = [pin.station for pin in out]
    duplicates = {s for s in stations if stations.count(s) > 1}
    if duplicates:
        raise ValueError(f"duplicate snap pins for: {sorted(duplicates)}")
    return out


def index(pins: list[Pin]) -> dict[str, Pin]:
    return {pin.station: pin for pin in pins}


def main() -> int:
    pins = load()
    print(f"{len(pins)} snap pin(s) in {DEFAULT_PATH}")
    for pin in pins:
        print(f"  {pin.station} -> way {pin.way_id} ({pin.decided_by}, {pin.date})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
