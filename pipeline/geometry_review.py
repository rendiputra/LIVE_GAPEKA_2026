"""Build the Phase 4 geometry review page (Leaflet).

Shows every station coloured by snap band, every non-routed or suspect segment in
red, and the full routes of the four pilot trains plus KA 1 and one long-distance
train chosen deterministically (the longest complete trip).

Only the needed GeoJSON is embedded so the file stays small.

Usage:
    python -m pipeline.geometry_review
"""

from __future__ import annotations

import json
from pathlib import Path

PARSED = Path("data/parsed")
REVIEW = Path("data/review")
OUT = REVIEW / "geometry_review.html"

BAND_COLOURS = {
    "ok": "#2e7d32",
    "review": "#f9a825",
    "rejected": "#b00020",
}

PILOT_TRAINS = ["249", "250", "259F", "260F", "1"]
MAX_EMBEDDED_POINTS = 60000


def _trips() -> list[dict]:
    out = []
    for book, name in ((1, "intercity_trips.json"), (2, "local_trips.json")):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            train.setdefault("book", book)
            out.append(train)
    return out


def pick_long_distance(trips: list[dict], geometry: dict) -> dict | None:
    """Deterministically pick one long, fully routed non-pilot trip."""
    best = None
    for train in trips:
        number = train["train_no"]
        if number in PILOT_TRAINS:
            continue
        key = f"{train['book']}:{number}"
        status = geometry["trip_status"].get(key, {})
        if status.get("status") != "complete":
            continue
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        length = 0.0
        for a, b in zip(codes, codes[1:], strict=False):
            seg = geometry["_by_pair"].get((a, b)) or geometry["_by_pair"].get((b, a))
            if seg and seg.get("length_m"):
                length += seg["length_m"]
        if best is None or length > best[0]:
            best = (length, train)
    return best[1] if best else None


def build() -> str:
    geometry = json.loads((PARSED / "segments.json").read_text(encoding="utf-8"))
    geometry["_by_pair"] = {(s["from_code"], s["to_code"]): s for s in geometry["segments"]}
    trips = _trips()
    long_train = pick_long_distance(trips, geometry)

    # Stations, coloured by snap band.
    station_points = []
    for code, snap in geometry["snaps"].items():
        if snap["lat"] is None:
            continue
        station_points.append(
            {
                "code": code,
                "lat": snap["lat"],
                "lon": snap["lon"],
                "band": snap["band"],
                "snap_m": snap["snap_distance_m"],
            }
        )

    # Problem segments only.
    problem = [
        {
            "from": s["from_code"],
            "to": s["to_code"],
            "quality": s["quality"],
            "reason": s["reason"],
            "coords": s["geometry"]["coordinates"] if s["geometry"] else [],
        }
        for s in geometry["segments"]
        if s["quality"] in ("osm_suspect", "straight_line", "unmeasured") and s["geometry"]
    ]

    # Selected routes.
    selected = [t for t in trips if t["train_no"] in PILOT_TRAINS]
    if long_train:
        selected.append(long_train)

    routes = []
    for train in selected:
        coords: list[list[float]] = []
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        total = 0.0
        hops = []
        for a, b in zip(codes, codes[1:], strict=False):
            seg = geometry["_by_pair"].get((a, b)) or geometry["_by_pair"].get((b, a))
            if not seg or not seg["geometry"]:
                hops.append({"from": a, "to": b, "quality": "unmeasured"})
                continue
            coords.extend(seg["geometry"]["coordinates"])
            total += seg["length_m"] or 0
            hops.append(
                {
                    "from": a,
                    "to": b,
                    "quality": seg["quality"],
                    "km": round((seg["length_m"] or 0) / 1000, 2),
                }
            )
        routes.append(
            {
                "train_no": train["train_no"],
                "book": train["book"],
                "name": train["name"],
                "length_km": round(total / 1000, 2),
                "coords": coords[:MAX_EMBEDDED_POINTS],
                "hops": hops,
            }
        )

    payload = {
        "stations": station_points,
        "problem": problem,
        "routes": routes,
        "long_train": long_train["train_no"] if long_train else None,
    }

    return _HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Phase 4 geometry review</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  body { margin: 0; font-family: -apple-system, system-ui, sans-serif; }
  #map { height: 74vh; }
  #panel { padding: 10px 14px; max-height: 26vh; overflow: auto; font-size: 13px; }
  .sw { display:inline-block; width:10px; height:10px; margin-right:5px; }
  table { border-collapse: collapse; font-size: 12px; }
  td, th { border: 1px solid #ccc; padding: 2px 6px; }
  h3 { margin: 12px 0 4px; }
</style>
</head>
<body>
<div id="panel">
  <h3>Legend</h3>
  <span class="sw" style="background:#2e7d32"></span>station snapped &le;300 m &nbsp;
  <span class="sw" style="background:#f9a825"></span>300 m&ndash;1 km &nbsp;
  <span class="sw" style="background:#b00020"></span>&gt;1 km / rejected &nbsp;
  <span class="sw" style="background:#1565c0"></span>route

  <h3>Selected trips</h3>
  <div id="routes"></div>
</div>
<div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const DATA = __DATA__;
const map = L.map('map').setView([-7.3, 110.5], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors (ODbL)'
}).addTo(map);

const bands = L.layerGroup().addTo(map);
const problems = L.layerGroup().addTo(map);
const routesLayer = L.layerGroup().addTo(map);

DATA.stations.forEach(s => {
  L.circleMarker([s.lat, s.lon], {
    radius: 3,
    color: s.band === 'ok' ? '#2e7d32' : (s.band === 'review' ? '#f9a825' : '#b00020'),
    fillOpacity: 0.85, weight: 1
  }).bindPopup(`<b>${s.code}</b><br>snap ${s.snap_m} m<br>band ${s.band}`).addTo(bands);
});

DATA.problem.forEach(p => {
  if (!p.coords.length) return;
  L.polyline(p.coords.map(c => [c[1], c[0]]), { color: '#b00020', weight: 2, dashArray: '4 3' })
    .bindPopup(`<b>${p.from} &rarr; ${p.to}</b><br>${p.quality}<br>${p.reason || ''}`).addTo(problems);
});

const colours = ['#1565c0', '#6a1b9a', '#00695c', '#ef6c00', '#283593', '#ad1457'];
DATA.routes.forEach((r, i) => {
  if (!r.coords.length) return;
  L.polyline(r.coords.map(c => [c[1], c[0]]), { color: colours[i % colours.length], weight: 2 })
    .bindPopup(`KA ${r.train_no}`).addTo(routesLayer);
});

const rt = document.getElementById('routes');
DATA.routes.forEach(r => {
  const div = document.createElement('div');
  div.innerHTML = `<b>KA ${r.train_no}</b> (${r.name || '?'}) &mdash; ${r.length_km} km, ${r.hops.length} hops`;
  const t = document.createElement('table');
  t.innerHTML = '<tr><th>from</th><th>to</th><th>quality</th><th>km</th></tr>' +
    r.hops.map(h => `<tr><td>${h.from}</td><td>${h.to}</td><td>${h.quality}</td><td>${h.km ?? '-'}</td></tr>`).join('');
  div.appendChild(t);
  rt.appendChild(div);
});

L.control.layers(null, { Stations: bands, 'Problem segments': problems, Routes: routesLayer }).addTo(map);
</script>
</body>
</html>
"""


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    size = OUT.stat().st_size / 1e6
    print(f"wrote {OUT} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
