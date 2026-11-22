"""Human segment reviews (ADR 005).

A routed segment above ``detour_suspect_ratio`` is flagged ``osm_suspect``. The
flag is not a verdict: the routing may be correct (a real loop) or the OSM data
may be missing a connection. This module reads the human decision from
``data/config/segment_reviews.yaml`` and tells build_geometry what to do.

The file is human-authored; nothing here writes it.

Usage:
    python -m pipeline.segment_reviews            # print what is loaded
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("data/config/segment_reviews.yaml")

ACCEPT_ROUTE = "accept_route"
NEEDS_BRIDGE = "needs_bridge"
DECISIONS = (ACCEPT_ROUTE, NEEDS_BRIDGE)

QUALITY_SUSPECT = "osm_suspect"
QUALITY_REVIEWED = "osm_routed_reviewed"


@dataclass(frozen=True)
class Review:
    from_code: str
    to_code: str
    decision: str
    reason: str
    decided_by: str
    date: str

    @property
    def key(self) -> tuple[str, str]:
        return (
            (self.from_code, self.to_code)
            if self.from_code < self.to_code
            else (
                self.to_code,
                self.from_code,
            )
        )


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def load(path: Path = DEFAULT_PATH) -> list[Review]:
    """Parse the review file. Unknown decisions are reported, not guessed."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if "reviews:" not in text:
        return []
    block = text.split("reviews:", 1)[1]

    reviews: list[Review] = []
    current: dict[str, str] | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- from:"):
            current = {"from": _unquote(stripped.split(":", 1)[1])}
            reviews.append(current)  # type: ignore[arg-type]
            continue
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = _unquote(value)

    out: list[Review] = []
    for entry in reviews:
        decision = entry.get("decision", "")
        if decision not in DECISIONS:
            continue
        if not entry.get("from") or not entry.get("to"):
            continue
        out.append(
            Review(
                from_code=entry["from"],
                to_code=entry["to"],
                decision=decision,
                reason=entry.get("reason", ""),
                decided_by=entry.get("decided_by", ""),
                date=entry.get("date", ""),
            )
        )
    return out


def index(reviews: list[Review]) -> dict[tuple[str, str], Review]:
    return {review.key: review for review in reviews}


def apply_quality(quality: str, review: Review | None) -> tuple[str, str]:
    """Return ``(quality, note)`` after applying a review.

    - ``accept_route`` on a suspect segment -> ``osm_routed_reviewed``
    - ``needs_bridge`` on a suspect segment -> unchanged, note kept
    - a review on a non-suspect segment is ignored and reported
    """
    if review is None:
        return quality, ""

    if quality != QUALITY_SUSPECT:
        return quality, (f"review ignored: segment was {quality}, not {QUALITY_SUSPECT}")

    if review.decision == ACCEPT_ROUTE:
        return QUALITY_REVIEWED, (
            f"human accepted the route on {review.date} ({review.decided_by}): {review.reason}"
        )

    # needs_bridge
    return QUALITY_SUSPECT, (
        f"human says this needs a bridge ({review.date}, {review.decided_by}): {review.reason}"
    )


def main() -> int:
    reviews = load()
    print(f"{len(reviews)} review(s) in {DEFAULT_PATH}")
    for review in reviews:
        print(f"  {review.key} {review.decision} by {review.decided_by} on {review.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
