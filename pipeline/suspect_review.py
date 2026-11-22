"""T2: suspect-segment review page and draft bridge candidates.

Produces:

- ``data/review/suspect_segments_review.html`` — a self-contained Leaflet page for
  every ``osm_suspect`` segment plus the segments behind the over-speed legs. It
  draws the routed polyline, the straight line, the nearby OSM rail ways, and the
  stations, with a table of the numbers a human needs to decide.
- ``data/config/geometry_bridges.draft.yaml`` — candidate bridges with evidence.
  COMMENTED OUT and NOT applied. Only a human decides.

Nothing here changes geometry.

Usage:
    python -m pipeline.suspect_review
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import build_geometry as bg
from pipeline.rail_graph import haversine_m, project_point_to_segment

REVIEW = Path("data/review")
SEGMENTS = Path("data/parsed/segments.json")
EXTRACT = Path("data/external/java_rail_graph.json")
OUT_HTML = REVIEW / "suspect_segments_review.html"
OUT_DRAFT = Path("data/config/geometry_bridges.draft.yaml")
SWEEP = REVIEW / "r1_engine_sweep.json"

MAX_WAYS_PER_SEGMENT = 60
WAY_RADIUS_M = 300.0
CANDIDATE_GAP_M = 20.0


def load(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def over_speed_segments(sweep: dict, snapshot) -> tuple[set[tuple[str, str]], dict]:
    """Expand each over-speed LEG into the SEGMENTS it actually traverses.

    A leg runs between two TIMED waypoints and may skip untimed rows, so the
    leg's endpoints are not necessarily adjacent stations. Mapping the leg to its
    real segments is what makes the per-segment "over-speed legs" count honest.
    """
    by_id = {trip.trip_id: trip for trip in snapshot.trips}
    pairs: set[tuple[str, str]] = set()
    counts: dict[tuple[str, str], int] = {}

    for row in sweep.get("fast_leg_examples", []):
        trip = by_id.get(row["trip_id"])
        if trip is None:
            continue
        # Locate the two waypoints by station code, preferring the pair that
        # matches the recorded from/to.
        start = end = None
        for index, waypoint in enumerate(trip.waypoints):
            if waypoint.station_code == row["from"] and start is None:
                start = index
            if waypoint.station_code == row["to"] and start is not None:
                end = index
                break
        if start is None or end is None or end <= start:
            key = (row["from"], row["to"])
            key = key if key[0] < key[1] else (key[1], key[0])
            pairs.add(key)
            counts[key] = counts.get(key, 0) + 1
            continue

        low = trip.waypoints[start].s_m
        high = trip.waypoints[end].s_m
        offset = 0.0
        for segment in trip.segments:
            seg_low, seg_high = offset, offset + segment.length_m
            offset = seg_high
            if seg_high <= low or seg_low >= high:
                continue
            key = (segment.from_code, segment.to_code)
            key = key if key[0] < key[1] else (key[1], key[0])
            pairs.add(key)
            counts[key] = counts.get(key, 0) + 1
    return pairs, counts


def trips_per_segment(trips: list[dict]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for train in trips:
        codes = [row["station_code"] for row in train["stops"] if row["station_code"]]
        for a, b in zip(codes, codes[1:], strict=False):
            key = (a, b) if a < b else (b, a)
            counts[key] = counts.get(key, 0) + 1
    return counts


def best_alternative_routes(
    segments: dict[tuple[str, str], dict], graph, config: dict
) -> dict[tuple[str, str], dict]:
    """For each segment, the best route achievable from a nearby alternative edge.

    A station between two adjacent tracks snaps to the nearest one, which can be
    a stub that forces a long detour. This records what the route would be from
    every other edge within the snap threshold, so the table can show whether the
    detour is a property of the LINE or of the chosen TRACK.
    """
    accepted = bg.accepted_coordinates()
    out: dict[tuple[str, str], dict] = {}

    for (a, b), segment in segments.items():
        if a not in accepted or b not in accepted:
            continue
        snap_b = graph.snap(
            b,
            (accepted[b]["lat"], accepted[b]["lon"]),
            config["snap_accept_m"],
            config["snap_review_m"],
        )
        point = (accepted[a]["lat"], accepted[a]["lon"])
        candidates = []
        seen: set[tuple[int, int]] = set()
        for edges in graph.adjacency.values():
            for edge in edges:
                if edge.a > edge.b or (edge.a, edge.b) in seen:
                    continue
                projected, distance, _t = project_point_to_segment(
                    point, graph.coords[edge.a], graph.coords[edge.b]
                )
                if distance > config["snap_accept_m"]:
                    continue
                seen.add((edge.a, edge.b))
                candidates.append((distance, edge.a, edge.b, projected, edge.way_id))
        candidates.sort()

        if snap_b.node_id is None:
            continue

        best = None
        for distance, ea, eb, projected, way in candidates[:6]:
            node = graph._split_edge(ea, eb, projected)
            result = bg.shortest_path(graph, node, snap_b.node_id)
            if result is None:
                continue
            if best is None or result[0] < best["routed_m"]:
                best = {
                    "routed_m": result[0],
                    "way_id": way,
                    "snap_distance_m": round(distance, 1),
                }
        if best:
            best["detour_ratio"] = (
                round(best["routed_m"] / segment["straight_m"], 3)
                if segment["straight_m"]
                else None
            )
            out[(a, b)] = best
    return out


def nearby_ways(ways: list[dict], node_coords: dict[int, tuple[float, float]], a: tuple, b: tuple):
    """Ways with at least one node inside the corridor around the straight line."""
    out = []
    # Cheap filter: bounding box of the segment expanded by the radius.
    deg = WAY_RADIUS_M / 111_000.0
    min_lat, max_lat = min(a[0], b[0]) - deg, max(a[0], b[0]) + deg
    min_lon, max_lon = min(a[1], b[1]) - deg, max(a[1], b[1]) + deg
    for way in ways:
        points = [node_coords[n] for n in way["nodes"] if n in node_coords]
        if not points:
            continue
        hit = any(min_lat <= lat <= max_lat and min_lon <= lon <= max_lon for lat, lon in points)
        if not hit:
            continue
        out.append(
            {
                "id": way["id"],
                "railway": way.get("railway"),
                "service": way.get("service"),
                "name": way.get("name"),
                "coords": [[round(lon, 5), round(lat, 5)] for lat, lon in points],
            }
        )
        if len(out) >= MAX_WAYS_PER_SEGMENT:
            break
    return out


def draft_candidates(extract: dict, graph, accepted: dict) -> list[dict]:
    """Dangling-endpoint pairs within CANDIDATE_GAP_M, with evidence. NOT applied."""
    from collections import deque

    component: dict[int, int] = {}
    members: dict[int, list[int]] = {}
    cid = 0
    for start in list(graph.adjacency):
        if start in component:
            continue
        queue = deque([start])
        component[start] = cid
        members[cid] = [start]
        while queue:
            node = queue.popleft()
            for edge in graph.adjacency[node]:
                if edge.b not in component:
                    component[edge.b] = cid
                    members[cid].append(edge.b)
                    queue.append(edge.b)
        cid += 1

    main = max(members, key=lambda key: len(members[key]))
    out = []
    for key, nodes in members.items():
        if key == main:
            continue
        best = None
        for node in nodes:
            for other in members[main]:
                distance = haversine_m(graph.coords[node], graph.coords[other])
                if best is None or distance < best[0]:
                    best = (distance, node, other)
                if distance < 0.5:
                    break
        if best and best[0] <= CANDIDATE_GAP_M:
            lat, lon = graph.coords[best[1]]
            out.append(
                {
                    "from_node": best[1],
                    "to_node": best[2],
                    "gap_m": round(best[0], 2),
                    "component_size": len(nodes),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "nearest_stations": sorted(
                        (
                            (
                                round(
                                    haversine_m((lat, lon), (entry["lat"], entry["lon"])) / 1000, 2
                                ),
                                code,
                            )
                            for code, entry in accepted.items()
                        )
                    )[:3],
                }
            )
    out.sort(key=lambda row: row["gap_m"])
    return out


def main() -> int:
    segments_payload = load(SEGMENTS)
    if not segments_payload:
        print("run build_geometry first")
        return 2
    sweep = load(SWEEP, {})
    extract = load(EXTRACT, {})
    config = bg.load_config()
    accepted = bg.accepted_coordinates()

    graph = bg.load_graph()
    graph.bridge_gaps(config.get("gap_bridge_m", 0.0))
    bg.apply_bridges(graph, bg.load_bridges())

    segments = {(row["from_code"], row["to_code"]): row for row in segments_payload["segments"]}
    # Segments are stored in one direction only; look them up both ways.
    undirected = {}
    for (a, b), row in segments.items():
        undirected[(a, b) if a < b else (b, a)] = row
    trips = bg.trips()
    usage = trips_per_segment(trips)
    from engine.snapshot import load as load_snapshot

    snapshot = load_snapshot()
    fast, over_speed_use = over_speed_segments(sweep, snapshot)

    selected: dict[tuple[str, str], dict] = {}
    for key, row in segments.items():
        if row["quality"] == "osm_suspect":
            selected[key] = row
    for key in fast:
        row = undirected.get(key)
        if row and row["quality"] != "unmeasured":
            selected[(row["from_code"], row["to_code"])] = row

    alternatives = best_alternative_routes(selected, graph, config)

    node_coords = {
        entry["id"]: (entry["lat"], entry["lon"]) for entry in extract.get("node_coords", [])
    }
    ways = extract.get("ways", [])

    rows = []
    for (a, b), row in sorted(selected.items()):
        straight = (accepted[a]["lat"], accepted[a]["lon"]) if a in accepted else None
        other = (accepted[b]["lat"], accepted[b]["lon"]) if b in accepted else None
        geometry = (row.get("geometry") or {}).get("coordinates") or []
        rows.append(
            {
                "from": a,
                "to": b,
                "quality": row["quality"],
                "straight_km": round(row["straight_m"] / 1000, 3),
                "routed_km": round(row["length_m"] / 1000, 3),
                "detour_ratio": row["detour_ratio"],
                "trips": usage.get((a, b) if a < b else (b, a), 0),
                "over_speed_legs": over_speed_use.get((a, b) if a < b else (b, a), 0),
                "best_alt": alternatives.get((a, b) if a < b else (b, a)),
                "route": [[round(c[1], 5), round(c[0], 5)] for c in geometry],
                "straight_line": (
                    [
                        [round(straight[1], 5), round(straight[0], 5)],
                        [round(other[1], 5), round(other[0], 5)],
                    ]
                    if straight and other
                    else None
                ),
                "ways": nearby_ways(ways, node_coords, straight, other)
                if straight and other
                else [],
                "reason": row.get("reason", ""),
            }
        )

    stations = {
        code: {
            "name": entry.get("name"),
            "lat": entry["lat"],
            "lon": entry["lon"],
        }
        for code, entry in accepted.items()
    }

    draft = draft_candidates(extract, graph, accepted)

    payload = {
        "generated": "suspect_segments_review",
        "segments": rows,
        "stations": stations,
        "draft_candidates": draft,
        "note": (
            "Report only. Nothing on this page is applied. The browser "
            "polyline is the routed geometry; grey dashed is the straight line."
        ),
    }
    OUT_HTML.write_text(
        _TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":"))),
        encoding="utf-8",
    )

    _write_draft(draft, rows, OUT_DRAFT)

    size = OUT_HTML.stat().st_size
    print(
        f"wrote {OUT_HTML} ({size / 1e6:.2f} MB, {len(rows)} segments) "
        f"and {OUT_DRAFT} ({len(draft)} candidates)"
    )
    for row in rows:
        alt = row["best_alt"]
        alt_text = (
            f" best alt way {alt['way_id']} {alt['routed_m'] / 1000:.3f} km "
            f"(ratio {alt['detour_ratio']})"
            if alt
            else ""
        )
        print(
            f"  {row['from']}-{row['to']} {row['quality']:13s} "
            f"{row['routed_km']:.3f} km vs {row['straight_km']:.3f} straight "
            f"(ratio {row['detour_ratio']}), {row['trips']} trips, "
            f"{row['over_speed_legs']} over-speed legs" + alt_text
        )
    return 0


def _write_draft(draft: list[dict], rows: list[dict], path: Path) -> None:
    lines = [
        "# CANDIDATE geometry bridges - DRAFT, NOT APPLIED.",
        "#",
        "# Generated by `python -m pipeline.suspect_review`. This file is EVIDENCE for",
        "# a human decision, not a decision. build_geometry reads only",
        "# data/config/geometry_bridges.yaml, never this file.",
        "#",
        "# A candidate joins two OSM nodes that are the same track but have no shared",
        "# node (a digitising seam). Copy an entry into geometry_bridges.yaml with",
        "# decided_by/date only after checking it on the review map.",
        "#",
        "# Evidence page: data/review/suspect_segments_review.html",
        "#",
        "# Schema (what an applied bridge looks like):",
        "#   bridges:",
        '#     - pair: ["<code>", "<code>"]',
        "#       from_node: <int>",
        "#       to_node: <int>",
        '#       reason: "<why>"',
        '#       evidence: "<file or measurement>"',
        '#       decided_by: "<your name>"',
        '#       date: "<YYYY-MM-DD>"',
        "",
        "bridges: []  # nothing applied",
        "",
        "# --- candidates, closest first (commented out on purpose) ---",
    ]
    for row in draft:
        near = ", ".join(f"{code} {km} km" for km, code in row["nearest_stations"])
        lines.extend(
            [
                "#",
                f"# gap {row['gap_m']} m, component of {row['component_size']} nodes",
                f"# at {row['lat']}, {row['lon']}; nearest stations: {near}",
                f"# - pair: [{row['nearest_stations'][0][1]!r}, {row['nearest_stations'][1][1]!r}]",
                f"#   from_node: {row['from_node']}",
                f"#   to_node: {row['to_node']}",
                f'#   reason: "{row["gap_m"]} m digitisation seam"',
                '#   evidence: "data/review/suspect_segments_review.html"',
                '#   decided_by: ""',
                '#   date: ""',
            ]
        )
    btt = next((row for row in rows if {row["from"], row["to"]} == {"BTT", "CS"}), None)
    lines.extend(
        [
            "",
            "# --- NOTE: the suspect segments are NOT all bridge candidates ---",
            "#",
        ]
    )
    if btt and btt["best_alt"]:
        alt = btt["best_alt"]
        lines.extend(
            [
                f"# For {btt['from']}-{btt['to']} the routed line is {btt['routed_km']} km vs",
                f"# {btt['straight_km']} km straight. There is no missing way: the station snaps",
                "# to a nearby stub. Routing from the adjacent way gives "
                f"{alt['routed_m'] / 1000:.3f} km",
                f"# (ratio {alt['detour_ratio']}). That is a SNAP problem (nearest edge vs the",
                "# track the trains use), not a bridge. It needs a human decision about",
                "# snap strategy, not a bridge entry.",
            ]
        )
    lines.extend(
        [
            "#",
            "# Where the best alternative track gives nearly the SAME distance (every",
            "# other suspect segment), the detour is a property of the line, and",
            "# `accept_route` in segment_reviews.yaml is the honest decision.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Suspect segment review - Gapeka 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
 body{margin:0;font-family:-apple-system,system-ui,sans-serif;font-size:13px}
 #banner{background:#0b5394;color:#fff;padding:8px 12px;font-weight:600}
 #map{height:60vh}
 #panel{padding:8px 12px;max-height:32vh;overflow:auto}
 table{border-collapse:collapse;margin-top:6px}
 td,th{border:1px solid #ccc;padding:2px 6px;text-align:left}
 th{background:#f4f4f4}
 tr.sel{background:#fff3cd}
 .num{text-align:right}
</style></head><body>
<div id="banner">Report only - nothing on this page is applied.
Routed polyline in red, straight line grey dashed, OSM ways thin.</div>
<div id="map"></div>
<div id="panel">
 <div><b>Suspect segments and the segments behind over-speed legs</b>
  &nbsp;|&nbsp; click a row to focus</div>
 <table id="tbl">
  <tr><th>from</th><th>to</th><th>quality</th><th class="num">straight km</th>
      <th class="num">routed km</th><th class="num">ratio</th><th class="num">trips</th>
      <th class="num">over-speed legs</th><th>best alt track</th></tr>
 </table>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const DATA = __DATA__;
const map = L.map('map').setView([-7.0,110.0],7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,
 attribution:'&copy; OpenStreetMap contributors (ODbL)'}).addTo(map);

const group = L.featureGroup().addTo(map);
const stationLayer = L.layerGroup().addTo(map);
const bounds = [];

DATA.segments.forEach((seg,j)=>{
  // straight line (grey dashed)
  if(seg.straight_line){
    L.polyline(seg.straight_line,{color:'#888',weight:2,dashArray:'6 6',opacity:0.8}).addTo(group);
  }
  // nearby OSM ways (thin)
  (seg.ways||[]).forEach(w=>{
    L.polyline(w.coords,{color:'#2e7d32',weight:1,opacity:0.55})
      .bindPopup(`way ${w.id}<br>railway=${w.railway||''}<br>service=${w.service||''}`)
      .addTo(group);
  });
  // routed polyline (red)
  if(seg.route && seg.route.length>1){
    const line=L.polyline(seg.route,{color:'#b00020',weight:3,opacity:0.95})
      .bindPopup(`<b>${seg.from} &rarr; ${seg.to}</b><br>`+
        `routed ${seg.routed_km} km, straight ${seg.straight_km} km<br>`+
        `ratio ${seg.detour_ratio}<br>${seg.reason||''}`)
      .addTo(group);
    line._segIndex=j;
    seg.route.forEach(c=>bounds.push(c));
  }
});

Object.entries(DATA.stations).forEach(([code,s])=>{
  if(!s.lat||!s.lon) return;
  L.circleMarker([s.lat,s.lon],{radius:3,color:'#1565c0',fillColor:'#1565c0',fillOpacity:0.9})
    .bindPopup(`<b>${code}</b><br>${s.name||''}`).addTo(stationLayer);
});

if(bounds.length) map.fitBounds(bounds,{padding:[20,20]});

const tbl=document.getElementById('tbl');
DATA.segments.forEach((seg,j)=>{
  const alt=seg.best_alt;
  const tr=document.createElement('tr');
  tr.innerHTML=`<td>${seg.from}</td><td>${seg.to}</td><td>${seg.quality}</td>`+
    `<td class="num">${seg.straight_km}</td><td class="num">${seg.routed_km}</td>`+
    `<td class="num">${seg.detour_ratio ?? ''}</td><td class="num">${seg.trips}</td>`+
    `<td class="num">${seg.over_speed_legs}</td>`+
    `<td>${alt?`way ${alt.way_id}: ${(alt.routed_m/1000).toFixed(3)} km `+
      `(ratio ${alt.detour_ratio})`:'-'}</td>`;
  tr.onclick=()=>{
    document.querySelectorAll('#tbl tr').forEach(r=>r.classList.remove('sel'));
    tr.classList.add('sel');
    if(seg.route && seg.route.length) map.fitBounds(seg.route,{padding:[40,40]});
  };
  tbl.appendChild(tr);
});
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
