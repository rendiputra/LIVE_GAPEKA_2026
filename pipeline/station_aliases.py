"""Station identity and name-conflict resolutions (H1, H8).

`data/config/station_aliases.yaml` is human-authored and tracked. It holds two
things:

- `stations:` official names, alternatives, kind and (H8) a `disambiguator` that
  distinguishes two stations printing the same name;
- `conflict_resolutions:` a recorded human decision about a name conflict.

Nothing here is inferred. A conflict without a resolution stays reported.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_PATH = Path("data/config/station_aliases.yaml")

STATION_FIELDS = ("official_name", "station_kind", "note", "disambiguator")


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def load(path: Path = DEFAULT_PATH) -> dict[str, dict]:
    """Parse the `stations:` block."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if "stations:" not in text:
        return {}
    # Stop at the next top-level key so conflict_resolutions never leaks in.
    block = text.split("stations:", 1)[1]
    for marker in ("\nconflict_resolutions:", "\n# ---"):
        if marker in block:
            block = block.split(marker, 1)[0]

    stations: dict[str, dict] = {}
    current: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("   ") and stripped.endswith(":"):
            current = stripped[:-1].strip()
            stations[current] = {}
            continue
        if current and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            if key in STATION_FIELDS:
                stations[current][key] = _unquote(value)
    return stations


def load_resolutions(path: Path = DEFAULT_PATH) -> dict[str, dict]:
    """Parse the `conflict_resolutions:` block, keyed by the conflicting name."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if "conflict_resolutions:" not in text:
        return {}
    block = text.split("conflict_resolutions:", 1)[1]

    resolutions: dict[str, dict] = {}
    current: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("   ") and stripped.endswith(":"):
            current = stripped[:-1].strip()
            resolutions[current] = {}
            continue
        if current and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = _unquote(value)
            if key == "codes":
                codes = value.strip("[]").split(",")
                resolutions[current]["codes"] = [
                    code.strip().strip('"') for code in codes if code.strip()
                ]
            elif key in ("resolution", "decided_by", "date", "note"):
                resolutions[current][key] = value
    return resolutions


def display_name(code: str, stations: dict[str, dict] | None = None) -> str:
    """Official name plus the disambiguator, for a UI that must not confuse them."""
    stations = stations if stations is not None else load()
    entry = stations.get(code, {})
    name = entry.get("official_name", code)
    extra = entry.get("disambiguator")
    return f"{name} ({extra})" if extra else name
