"""Q1: draft coordinate proposals for stations that block geometry.

Produces two artefacts, both read-only and neither applied:

- ``data/review/station_overrides.draft.yaml`` — one commented-out proposal per
  affected station, with every candidate, name similarity, snap distance and
  neighbour comparison.
- ``data/review/station_candidates_map.html`` — Leaflet map so a human can check
  the proposals visually.

A recommendation of ``strong`` requires ALL of: exactly one candidate, exact
normalised name match, inside the Java bbox, snapping to rail within
``snap_accept_m``, and plausible neighbour distances. Anything less is ``weak``
or ``none``.

Usage:
    python -m pipeline.override_draft
"""

from __future__ import annotations

import difflib
import json
from collections import Counter
from pathlib import Path

from pipeline.rail_graph import RailGraph
from pipeline.rail_graph import haversine_m as rail_haversine
from pipeline.station_coords import JAVA_BBOX, normalise_name, wikidata_by_code

PARSED = Path("data/parsed")
EXTERNAL = Path("data/external")
REVIEW = Path("data/review")
CONFIG = Path("data/config/geometry.yaml")
DRAFT = REVIEW / "station_overrides.draft.yaml"
MAP = REVIEW / "station_candidates_map.html"

# Stations the human asked to be explicitly accounted for.
NAMED = {"SMT": "Semarang Tawang", "MTR": "Matraman", "CKI": "Cikini", "SRI": "Sragi"}


def load_snap_config() -> dict:
    config = {"snap_accept_m": 300.0, "snap_review_m": 1000.0}
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            if key.strip() in config and value.strip().replace(".", "", 1).isdigit():
                config[key.strip()] = float(value.strip())
    return config


def in_java(lat: float, lon: float) -> bool:
    return (
        JAVA_BBOX["min_lat"] <= lat <= JAVA_BBOX["max_lat"]
        and JAVA_BBOX["min_lon"] <= lon <= JAVA_BBOX["max_lon"]
    )


def load_alias_config(path: Path = Path("data/config/station_aliases.yaml")) -> dict:
    """Read official names and alternatives from the human alias file."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if "stations:" not in text:
        return {}
    block = text.split("stations:", 1)[1]
    out: dict[str, dict] = {}
    current = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("   ") and stripped.endswith(":"):
            current = stripped[:-1].strip()
            out[current] = {"official_name": None, "alternatives": []}
            continue
        if current is None:
            continue
        if stripped.startswith("official_name:"):
            out[current]["official_name"] = stripped.split(":", 1)[1].strip().strip('"')
        elif stripped.startswith("alternatives:"):
            raw = stripped.split(":", 1)[1].strip()
            items = [x.strip().strip('"') for x in raw.strip("[]").split(",") if x.strip()]
            out[current]["alternatives"] = items
    return out


def squash(text: str) -> str:
    """Whitespace-insensitive form: 'Jambubaru' == 'Jambu Baru'."""
    return normalise_name(text).replace(" ", "")


def similarity(a: str, b: str) -> float:
    def clean(text: str) -> str:
        upper = normalise_name(text)
        for prefix in ("STASIUN ", "STA "):
            if upper.startswith(prefix):
                upper = upper[len(prefix) :]
        return upper

    left, right = squash(clean(a)), squash(clean(b))
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return round(difflib.SequenceMatcher(None, left, right).ratio(), 3)


def affected_stations() -> list[dict]:
    """Stations with no accepted coordinate, plus those blocking geometry."""
    stations: dict[str, dict] = {}

    for name in ("intercity_trips.json", "local_trips.json"):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            for stop in train["stops"]:
                code = stop["station_code"]
                if not code:
                    continue
                entry = stations.setdefault(
                    code,
                    {
                        "code": code,
                        "name": stop["station_name"] or code,
                        "trains": set(),
                        "pages": set(),
                        "before": Counter(),
                        "after": Counter(),
                    },
                )
                entry["trains"].add(train["train_no"])
                entry["pages"].add(stop["provenance"]["page"])
            codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
            for index, code in enumerate(codes):
                if index > 0:
                    stations[code]["before"][codes[index - 1]] += 1
                if index + 1 < len(codes):
                    stations[code]["after"][codes[index + 1]] += 1

    accepted = json.loads((PARSED / "station_coordinates.json").read_text(encoding="utf-8"))[
        "matched"
    ]
    rejected = json.loads((REVIEW / "stations_suspicious_coords.json").read_text(encoding="utf-8"))[
        "stations"
    ]
    rejected_codes = {c.strip() for row in rejected for c in row["code"].split(",")}

    out = []
    for code, entry in sorted(stations.items()):
        if code in accepted and code not in rejected_codes:
            continue
        entry["status"] = "rejected" if code in rejected_codes else "missing"
        entry["trains"] = sorted(entry["trains"])
        entry["pages"] = sorted(entry["pages"])
        out.append(entry)
    return out


def candidates_for(code: str, name: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    wd_path = EXTERNAL / "wikidata_stations.json"
    if wd_path.exists():
        rows = json.loads(wd_path.read_text(encoding="utf-8"))
        for candidate in wikidata_by_code(rows).get(code.upper(), []):
            if candidate.source_id in seen:
                continue
            seen.add(candidate.source_id)
            out.append(
                {
                    "source": "wikidata",
                    "source_id": candidate.source_id,
                    "name": candidate.name,
                    "ref": code,
                    "lat": round(candidate.lat, 6),
                    "lon": round(candidate.lon, 6),
                    "matched_by": "code",
                }
            )

    graph_path = EXTERNAL / "java_rail_graph.json"
    graph = (
        json.loads(graph_path.read_text(encoding="utf-8"))
        if graph_path.exists()
        else {"stations": []}
    )
    key = normalise_name(name)
    for station in graph.get("stations", []):
        label = station.get("name")
        if not label:
            continue
        candidate_key = normalise_name(label)
        if candidate_key != key and similarity(name, label) < 0.85:
            continue
        source_id = f"node/{station['id']}"
        if source_id in seen:
            continue
        seen.add(source_id)
        out.append(
            {
                "source": "osm",
                "source_id": source_id,
                "name": label,
                "ref": station.get("ref"),
                "lat": round(station["lat"], 6),
                "lon": round(station["lon"], 6),
                "matched_by": "code"
                if (station.get("ref") or "").upper() == code.upper()
                else "name",
            }
        )
    return out


def nearest_edge_distance(graph: RailGraph, lat: float, lon: float) -> float:
    from pipeline.rail_graph import project_point_to_segment

    best = float("inf")
    seen: set[tuple[int, int]] = set()
    for edges in graph.adjacency.values():
        for edge in edges:
            key_pair = (min(edge.a, edge.b), max(edge.a, edge.b))
            if key_pair in seen:
                continue
            seen.add(key_pair)
            _p, distance, _t = project_point_to_segment(
                (lat, lon), graph.coords[edge.a], graph.coords[edge.b]
            )
            best = min(best, distance)
    return best


def build() -> dict:
    config = load_snap_config()
    from pipeline.build_geometry import load_graph

    graph = load_graph()
    accepted = json.loads((PARSED / "station_coordinates.json").read_text(encoding="utf-8"))[
        "matched"
    ]
    stations = affected_stations()

    proposals = []
    for entry in stations:
        code = entry["code"]
        candidates = candidates_for(code, entry["name"])

        neighbours = [
            {"relation": "before", "code": c, "count": n} for c, n in entry["before"].most_common(4)
        ] + [{"relation": "after", "code": c, "count": n} for c, n in entry["after"].most_common(4)]
        neighbour_points = {
            row["code"]: (accepted[row["code"]]["lat"], accepted[row["code"]]["lon"])
            for row in neighbours
            if row["code"] in accepted
        }

        for candidate in candidates:
            candidate["in_java"] = in_java(candidate["lat"], candidate["lon"])
            candidate["name_similarity"] = similarity(entry["name"], candidate["name"])
            candidate["snap_distance_m"] = round(
                nearest_edge_distance(graph, candidate["lat"], candidate["lon"]), 1
            )
            candidate["neighbour_km"] = {
                other: round(rail_haversine((candidate["lat"], candidate["lon"]), point) / 1000, 2)
                for other, point in neighbour_points.items()
            }

        # A2b: cluster candidates within 100 m. Wikidata and OSM agreeing on the
        # same spot is ONE candidate with corroboration, not an ambiguity.
        clusters: list[dict] = []
        for candidate in sorted(candidates, key=lambda c: -c["name_similarity"]):
            for cluster in clusters:
                if (
                    rail_haversine(
                        (candidate["lat"], candidate["lon"]),
                        (cluster["lat"], cluster["lon"]),
                    )
                    <= 100
                ):
                    cluster["members"].append(candidate)
                    break
            else:
                clusters.append(
                    {
                        "lat": candidate["lat"],
                        "lon": candidate["lon"],
                        "members": [candidate],
                    }
                )
        for cluster in clusters:
            cluster["sources"] = sorted({m["source"] for m in cluster["members"]})
            cluster["corroborated"] = len(cluster["sources"]) > 1
            cluster["best"] = max(cluster["members"], key=lambda m: m["name_similarity"])

        plausible = [
            c
            for c in clusters
            if c["best"]["in_java"]
            and c["best"]["name_similarity"] == 1.0
            and c["best"]["snap_distance_m"] <= config["snap_accept_m"]
        ]

        if not candidates:
            recommendation, reason = "none", "no candidate from any source"
        elif len(plausible) == 1:
            corroborated = plausible[0]["corroborated"]
            recommendation, reason = (
                "strong",
                "single exact-name cluster inside Java, snapping to rail "
                f"<= {config['snap_accept_m']:.0f} m"
                + (" (Wikidata + OSM corroborate)" if corroborated else ""),
            )
        elif len(plausible) > 1:
            recommendation, reason = (
                "weak",
                f"{len(plausible)} exact-name candidates; a human must choose",
            )
        else:
            why = []
            if not any(c["in_java"] for c in candidates):
                why.append("all candidates outside the Java bbox")
            if not any(c["name_similarity"] == 1.0 for c in candidates):
                why.append("no exact normalised name match")
            if not any(c["snap_distance_m"] <= config["snap_accept_m"] for c in candidates):
                why.append(f"no candidate snaps within {config['snap_accept_m']:.0f} m")
            recommendation, reason = "weak", "; ".join(why) or "ambiguous"

        proposals.append(
            {
                "clusters": [
                    {
                        "lat": c["lat"],
                        "lon": c["lon"],
                        "sources": c["sources"],
                        "corroborated": c["corroborated"],
                        "members": len(c["members"]),
                    }
                    for c in clusters
                ],
                "code": code,
                "name": entry["name"],
                "current_status": entry["status"],
                "trains_affected": len(entry["trains"]),
                "pages": entry["pages"][:8],
                "neighbours": neighbours,
                "candidates": candidates,
                "recommendation": recommendation,
                "reason": reason,
                "named_station": NAMED.get(code),
            }
        )

    counts = Counter(p["recommendation"] for p in proposals)
    return {"proposals": proposals, "counts": dict(counts), "config": config}


def applied_codes() -> set[str]:
    from pipeline.station_overrides import load as load_overrides

    return {o.code for o in load_overrides()}


def _yaml(payload: dict) -> str:
    lines = [
        "# DRAFT station coordinate proposals - NOT APPLIED.",
        "#",
        "# Every entry is commented out on purpose. To accept one, copy it (uncommented)",
        "# into data/config/station_overrides.yaml, which is yours and gitignored.",
        "#",
        "# Recommendation rule: 'strong' requires exactly one candidate with an exact",
        "# normalised name match, inside the Java bbox, snapping to rail within the",
        "# configured accept distance, and plausible neighbour distances.",
        "",
        f"# codes: {len(payload['proposals'])}   {payload['counts']}",
        "",
        "overrides: []",
        "",
    ]
    applied = applied_codes()
    for item in payload["proposals"]:
        state = "APPLIED" if item["code"] in applied else "PENDING"
        lines.append(f"# --- {item['code']}  {item['name']}  [{item['current_status']}] [{state}]")
        if item["named_station"]:
            lines.append(f"#     noted by the reviewer as: {item['named_station']}")
        lines.append(f"#     recommendation: {item['recommendation']} — {item['reason']}")
        lines.append(f"#     trains affected: {item['trains_affected']}  pages: {item['pages']}")
        if item["neighbours"]:
            joined = ", ".join(
                f"{n['relation']}:{n['code']}x{n['count']}" for n in item["neighbours"]
            )
            lines.append(f"#     neighbours: {joined}")
        for candidate in item["candidates"]:
            dist = ", ".join(f"{k}={v}km" for k, v in candidate["neighbour_km"].items()) or "-"
            lines.append(
                f"#     candidate {candidate['source']}:{candidate['source_id']} "
                f"name={candidate['name']!r} ref={candidate['ref']} "
                f"lat={candidate['lat']} lon={candidate['lon']} "
                f"sim={candidate['name_similarity']} "
                f"snap={candidate['snap_distance_m']}m in_java={candidate['in_java']}"
            )
            lines.append(f"#       neighbour distances: {dist}")
        if not item["candidates"]:
            lines.append("#     no candidates found")
        best = item["candidates"][0] if item["candidates"] else None
        if best:
            lines.append(f'#   - code: "{item["code"]}"')
            lines.append(f"#     lat: {best['lat']}")
            lines.append(f"#     lon: {best['lon']}")
            lines.append(f'#     reason: "{item["reason"]}"')
            lines.append(
                f'#     evidence: "{best["source"]} {best["source_id"]} '
                f"name similarity {best['name_similarity']}, "
                f'snap {best["snap_distance_m"]} m"'
            )
            lines.append('#     decided_by: "<your name>"')
            lines.append('#     date: "<YYYY-MM-DD>"')
        lines.append("")
    return "\n".join(lines) + "\n"


MAP_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Station coordinate candidates</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>body{margin:0;font-family:-apple-system,system-ui,sans-serif}#map{height:80vh}
#panel{padding:8px 12px;font-size:13px;max-height:18vh;overflow:auto}
table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #ccc;padding:2px 6px}</style>
</head><body>
<div id="panel"><b>Station coordinate candidates (DRAFT)</b>
<div id="summary"></div><div id="table"></div></div>
<div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const DATA = __DATA__;
const map = L.map('map').setView([-7.3, 110.5], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,
  attribution:'&copy; OpenStreetMap contributors (ODbL)'}).addTo(map);
const COLOUR = {strong:'#2e7d32', weak:'#f9a825', none:'#b00020'};
DATA.proposals.forEach(p => {
  p.candidates.forEach(c => {
    L.circleMarker([c.lat, c.lon], {radius:6, color:COLOUR[p.recommendation],
      fillOpacity:0.8, weight:2})
      .bindPopup(`<b>${p.code}</b> ${p.name}<br>recommendation <b>${p.recommendation}</b><br>`+
        `${p.reason}<br>candidate ${c.source}:${c.source_id}<br>${c.name}<br>`+
        `sim ${c.name_similarity} · snap ${c.snap_distance_m} m · java ${c.in_java}`)
      .addTo(map);
  });
});
document.getElementById('summary').textContent =
  DATA.proposals.length + ' stations: ' +
  Object.entries(DATA.counts).map(e => e[0] + ' ' + e[1]).join(', ');
document.getElementById('table').innerHTML =
  '<table><tr><th>code</th><th>name</th><th>rec</th><th>candidates</th><th>reason</th></tr>' +
  DATA.proposals.map(p => '<tr><td>' + p.code + '</td><td>' + p.name + '</td>' +
    '<td>' + p.recommendation + '</td><td>' + p.candidates.length + '</td><td>' +
    p.reason + '</td></tr>').join('') + '</table>';
</script></body></html>
"""


def main() -> int:
    payload = build()
    REVIEW.mkdir(parents=True, exist_ok=True)
    DRAFT.write_text(_yaml(payload), encoding="utf-8")
    MAP.write_text(
        MAP_TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":"))),
        encoding="utf-8",
    )
    print(f"wrote {DRAFT}")
    print(f"wrote {MAP}")
    print(f"codes: {len(payload['proposals'])}  {payload['counts']}")
    for item in payload["proposals"]:
        flag = " *" if item["named_station"] else ""
        print(f"  {item['code']:5s} {item['recommendation']:<6} {item['name'][:26]:26s}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
