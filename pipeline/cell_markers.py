"""Cell-marker whitelist (Q1).

The Gapeka PDF prints tokens such as ``Berh`` and ``Sb`` in the Datang/Berangkat
columns and never defines them (ADR 003). This module loads the human-approved
whitelist from ``data/config/cell_markers.yaml`` and answers one question: is
this token an accepted marker?

Tokens are handled **neutrally**:

- ``time = null`` — no time is invented;
- ``time_source = "marker"``;
- the raw token is preserved verbatim;
- the row's ``stop_type`` becomes ``unknown_untimed`` — we never claim the row is
  a stop or a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("data/config/cell_markers.yaml")

# Minimal parser for the tiny YAML subset we need, so the pipeline keeps a
# single runtime dependency (PyMuPDF). Only the ``enabled:`` block is read; the
# file's shape is fixed and unit-tested.
_ENABLED_RE = re.compile(r"^  ([A-Za-z][A-Za-z0-9_.]*):\s*$", re.MULTILINE)


@dataclass(frozen=True)
class MarkerSet:
    """The accepted marker tokens, upper-cased for comparison."""

    tokens: frozenset[str]

    def is_marker(self, text: str) -> bool:
        stripped = text.strip()
        return bool(stripped) and stripped.upper() in self.tokens


EMPTY_MARKERS = MarkerSet(frozenset())


def load(config: Path = DEFAULT_CONFIG) -> MarkerSet:
    """Load the enabled marker tokens from the config file."""
    if not config.exists():
        return EMPTY_MARKERS
    text = config.read_text(encoding="utf-8")

    # Everything after the "enabled:" key, up to the next top-level key.
    try:
        enabled_block = text.split("enabled:", 1)[1]
    except IndexError:
        return EMPTY_MARKERS
    for stop in ("observed_not_enabled:", "\n#"):
        if stop in enabled_block:
            enabled_block = enabled_block.split(stop, 1)[0]

    tokens = {match.group(1).upper() for match in _ENABLED_RE.finditer(enabled_block)}
    return MarkerSet(frozenset(tokens))


def describe(config: Path = DEFAULT_CONFIG) -> dict:
    """Report the whitelist and the observed-but-disabled tokens."""
    markers = load(config)
    disabled: list[str] = []
    if config.exists():
        text = config.read_text(encoding="utf-8")
        if "observed_not_enabled:" in text:
            block = text.split("observed_not_enabled:", 1)[1]
            disabled = re.findall(r"-\s*token:\s*([A-Za-z0-9_.]+)", block)
    return {
        "enabled": sorted(markers.tokens),
        "observed_not_enabled": disabled,
        "config": str(config),
    }
