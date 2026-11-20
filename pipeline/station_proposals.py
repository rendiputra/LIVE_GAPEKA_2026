"""Build evidence dossiers for stations whose coordinate is disputed (Q4 / S2).

For every flagged code this writes one entry with:

- the neighbouring stations in trips (before/after, with counts);
- every candidate coordinate (Wikidata, OSM) with its distance to those
  neighbours;
- a **plausible** choice, clearly marked as a proposal.

Nothing here is applied. `data/config/station_overrides.yaml` is authored by the
human; this module only prepares the evidence.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.cross_checks import haversine_km
from pipeline.station_coords import (
    JAVA_BBOX,
    normalise_name,
    osm_candidates,
    wikidata_by_code,
    wikidata_by_name,
)

PARSED = Path("data/parsed")
REVIEW = Path("data/review")
EXTERNAL = Path("data/external")
OUT = REVIEW / "station_override_proposals.yaml"
OVERRIDES = Path("data/config/station_overrides.yaml")


def neighbours_from_trips() -> dict[str, dict[str, Counter]]:
    """For each code: how often each other code precedes/follows it."""
    before: dict[str, Counter] = defaultdict(Counter)
    after: dict[str, Counter] = defaultdict(Counter)
    for name in ("intercity_trips.json", "local_trips.json"):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            stops = train["stops"]
            for index, stop in enumerate(stops):
                code = stop["station_code"]
                if not code:
                    continue
                if index > 0 and stops[index - 1]["station_code"]:
                    before[code][stops[index - 1]["station_code"]] += 1
                if index + 1 < len(stops) and stops[index + 1]["station_code"]:
                    after[code][stops[index + 1]["station_code"]] += 1
    return {"before": before, "after": after}


def flagged_codes() -> list[dict]:
    """Codes with a disputed or missing coordinate, with the reason."""
    flagged: dict[str, str] = {}

    suspicious = REVIEW / "stations_suspicious_coords.json"
    if suspicious.exists():
        for row in json.loads(suspicious.read_text(encoding="utf-8"))["stations"]:
            for code in row["code"].split(","):
                flagged[code.strip()] = row.get("reason") or "implausible neighbour distance"

    ambiguous = REVIEW / "stations_ambiguous.json"
    if ambiguous.exists():
        for row in json.loads(ambiguous.read_text(encoding="utf-8"))["stations"]:
            flagged.setdefault(row["code"], row["reason"])

    unmatched = REVIEW / "stations_unmatched.json"
    if unmatched.exists():
        for row in json.loads(unmatched.read_text(encoding="utf-8"))["stations"]:
            flagged.setdefault(row["code"], "no candidate from any source")

    return [{"code": code, "reason": reason} for code, reason in sorted(flagged.items())]


def candidates_for(code: str, name: str) -> list[dict]:
    """All candidate coordinates for a code from both sources."""
    out: list[dict] = []

    wd_path = EXTERNAL / "wikidata_stations.json"
    if wd_path.exists():
        rows = json.loads(wd_path.read_text(encoding="utf-8"))
        for candidate in wikidata_by_code(rows).get(code.upper(), []):
            out.append(
                {
                    "source": "wikidata",
                    "source_id": candidate.source_id,
                    "label": candidate.name,
                    "lat": round(candidate.lat, 6),
                    "lon": round(candidate.lon, 6),
                    "matched_by": "code",
                }
            )
        key = normalise_name(name)
        for candidate in wikidata_by_name(rows).get(key, []):
            if any(c["source_id"] == candidate.source_id for c in out):
                continue
            out.append(
                {
                    "source": "wikidata",
                    "source_id": candidate.source_id,
                    "label": candidate.name,
                    "lat": round(candidate.lat, 6),
                    "lon": round(candidate.lon, 6),
                    "matched_by": "name",
                }
            )

    osm_path = EXTERNAL / "osm_stations.json"
    if osm_path.exists():
        rows = json.loads(osm_path.read_text(encoding="utf-8"))
        by_name = osm_candidates(rows)
        for candidate in by_name.get(normalise_name(name), []):
            out.append(
                {
                    "source": "osm",
                    "source_id": candidate.source_id,
                    "label": candidate.name,
                    "lat": round(candidate.lat, 6),
                    "lon": round(candidate.lon, 6),
                    "matched_by": "name",
                }
            )
    return out


def coordinate_of(code: str, accepted: dict) -> tuple[float, float] | None:
    entry = accepted.get(code)
    if entry is None:
        return None
    return (entry["lat"], entry["lon"])


def build() -> dict:
    neighbours = neighbours_from_trips()
    accepted_path = PARSED / "station_coordinates.json"
    accepted = (
        json.loads(accepted_path.read_text(encoding="utf-8"))["matched"]
        if accepted_path.exists()
        else {}
    )

    names: dict[str, str] = {}
    for name in ("intercity_trips.json", "local_trips.json"):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            for stop in train["stops"]:
                if stop["station_code"] and stop["station_name"]:
                    names.setdefault(stop["station_code"], stop["station_name"])

    dossiers = []
    for flagged in flagged_codes():
        code = flagged["code"]
        name = names.get(code, code)
        before = neighbours["before"].get(code, Counter()).most_common(5)
        after = neighbours["after"].get(code, Counter()).most_common(5)

        assembled = []
        for candidate in candidates_for(code, name):
            distances = {}
            for other, _count in before + after:
                point = coordinate_of(other, accepted)
                if point is None:
                    continue
                distances[other] = round(
                    haversine_km((candidate["lat"], candidate["lon"]), point), 1
                )
            candidate["neighbour_distances_km"] = distances
            candidate["neighbour_distance_sum"] = round(sum(distances.values()), 1)
            assembled.append(candidate)

        # A candidate outside Java cannot be the right station, regardless of how
        # few neighbours it could be compared against.
        for candidate in assembled:
            candidate["in_java_bbox"] = (
                JAVA_BBOX["min_lat"] <= candidate["lat"] <= JAVA_BBOX["max_lat"]
                and JAVA_BBOX["min_lon"] <= candidate["lon"] <= JAVA_BBOX["max_lon"]
            )

        plausible = None
        ranked = [c for c in assembled if c.get("in_java_bbox")]
        if ranked:
            # The plausible choice is the candidate closest to the route
            # neighbours overall. This is a PROPOSAL, not a decision.
            ranked = sorted(ranked, key=lambda c: c["neighbour_distance_sum"])
            plausible = {
                "source": ranked[0]["source"],
                "source_id": ranked[0]["source_id"],
                "lat": ranked[0]["lat"],
                "lon": ranked[0]["lon"],
                "rule": "smallest total distance to route neighbours",
            }

        if assembled and plausible is None:
            rejected = [c for c in assembled if not c.get("in_java_bbox")]
            if rejected:
                # Record every out-of-Java candidate as rejected evidence, not a choice.
                plausible_note = (
                    "all candidates are outside the Java bounding box; "
                    "no plausible coordinate exists"
                )
            else:
                plausible_note = "no candidate"
        else:
            plausible_note = ""

        dossiers.append(
            {
                "code": code,
                "proposal_note": plausible_note,
                "printed_name": name,
                "flag_reason": flagged["reason"],
                "neighbours_before": [{"code": c, "count": n} for c, n in before],
                "neighbours_after": [{"code": c, "count": n} for c, n in after],
                "candidates": assembled,
                "plausible_proposal": plausible,
                "note": "PROPOSAL ONLY. Not applied. The human decides in station_overrides.yaml.",
            }
        )

    return {
        "note": (
            "Generated evidence for disputed station coordinates. Nothing here is "
            "applied; decide in data/config/station_overrides.yaml."
        ),
        "generated_by": "python -m pipeline.station_proposals",
        "count": len(dossiers),
        "proposals": dossiers,
    }


def write_yaml(payload: dict, path: Path) -> None:
    """Emit the dossier as readable YAML without adding a YAML dependency."""
    lines = [
        "# Evidence for disputed station coordinates (Q4).",
        "# PROPOSALS ONLY - nothing here is applied.",
        "# To accept a coordinate, author data/config/station_overrides.yaml instead.",
        "",
        f"count: {payload['count']}",
        "proposals:",
    ]
    for item in payload["proposals"]:
        lines.append(f"  - code: {json.dumps(item['code'])}")
        lines.append(f"    printed_name: {json.dumps(item['printed_name'])}")
        lines.append(f"    flag_reason: {json.dumps(item['flag_reason'])}")
        lines.append("    neighbours_before:")
        for row in item["neighbours_before"] or [{"code": None, "count": 0}]:
            lines.append(f"      - {{code: {json.dumps(row['code'])}, count: {row['count']}}}")
        lines.append("    neighbours_after:")
        for row in item["neighbours_after"] or [{"code": None, "count": 0}]:
            lines.append(f"      - {{code: {json.dumps(row['code'])}, count: {row['count']}}}")
        if not item["candidates"]:
            lines.append("    candidates: []")
        else:
            lines.append("    candidates:")
            for candidate in item["candidates"]:
                dist = ", ".join(
                    f"{k}: {v}" for k, v in candidate["neighbour_distances_km"].items()
                )
                lines.append(
                    f"      - {{source: {candidate['source']}, "
                    f"source_id: {json.dumps(candidate['source_id'])}, "
                    f"label: {json.dumps(candidate['label'])}, "
                    f"lat: {candidate['lat']}, lon: {candidate['lon']}, "
                    f"matched_by: {candidate['matched_by']}, "
                    f"neighbour_km: {{{dist}}}}}"
                )
        if item["plausible_proposal"]:
            choice = item["plausible_proposal"]
            lines.append(
                f"    plausible_proposal: {{source: {choice['source']}, "
                f"source_id: {json.dumps(choice['source_id'])}, "
                f"lat: {choice['lat']}, lon: {choice['lon']}, "
                f"rule: {json.dumps(choice['rule'])}}}"
            )
        else:
            lines.append("    plausible_proposal: null")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_override_schema() -> None:
    """Create the empty, human-authored override file with a schema comment."""
    if OVERRIDES.exists():
        return
    OVERRIDES.write_text(
        """# Station coordinate overrides - AUTHORED BY THE HUMAN.
#
# The pipeline never writes this file. build_db reads it and, for each entry,
# inserts the coordinate with coord_status = "override" and coord_source =
# "override", plus a row in station_coord_candidates marked "accepted".
#
# Schema:
#   overrides:
#     - code:      "<station code as printed in the PDF>"
#       lat:       <float>
#       lon:       <float>
#       reason:    "<why this coordinate is right>"
#       evidence:  "<where the value came from: a reference, a survey, a link>"
#       decided_by: "<your name>"
#       date:      "<YYYY-MM-DD>"
#
# Leave `overrides` empty until you have decided. An override replaces any
# external match for that code.
overrides: []
""",
        encoding="utf-8",
    )


def main() -> int:
    payload = build()
    REVIEW.mkdir(parents=True, exist_ok=True)
    write_yaml(payload, OUT)
    write_override_schema()
    print(f"wrote {OUT} ({payload['count']} codes)")
    print(f"override file: {OVERRIDES}")
    for item in payload["proposals"]:
        choice = item["plausible_proposal"]
        label = f"{choice['source']}:{choice['source_id']}" if choice else "no candidate"
        print(f"  {item['code']:5s} {item['printed_name'][:28]:28s} -> {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
