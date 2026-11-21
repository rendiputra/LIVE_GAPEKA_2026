"""R2: self-contained Leaflet replay page for the position engine.

Precomputes frames for 2026-12-01 at 30 s steps and embeds them with a time
slider, play/pause, speed control and a printed-vs-engine table.

Trip selection is explicit and stated in the page itself. The pilots KA 249 and
KA 250 are NOT loadable (station SRI snaps 1,806 m from rail, above the
1,000 m review limit), so the page says so rather than substituting silently.

Usage:
    python -m pipeline.engine_replay
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from engine.model import Policy
from engine.position import _legs, _position_for
from engine.snapshot import load

OUT = Path("data/review/engine_replay.html")
SWEEP_DATE = date(2026, 12, 1)
STEP_S = 30
MAX_BYTES = 15 * 1024 * 1024

# train_no -> why it is on the page
CHOSEN: dict[str, str] = {
    "259F": "pilot; fakultatif; exercises the shown/hidden policy",
    "260F": "pilot; crosses midnight (day_offset 1)",
    "265": "has_fallback geometry; shows flagged output",
    "351": "Book 2; complete_estimated (a bypassed waypoint)",
    "13": "Book 1; longest trip (574 km, 87 waypoints); complete_estimated",
    "436": "Book 2; complete geometry (no bypass, no fallback)",
    "183": "Book 1; has_fallback; long trip",
}

NOT_LOADABLE = {
    "249": (
        "not loaded: station SRI snaps 1,806 m from rail (> snap_review_m 1,000) -> has_unmeasured"
    ),
    "250": "not loaded: same SRI snap failure as KA 249",
}


def pick_trips(snapshot) -> tuple[list, list[dict]]:
    by_no: dict[str, object] = {}
    for trip in snapshot.trips:
        by_no.setdefault(trip.train_no, trip)

    picked, notes = [], []
    for number, reason in CHOSEN.items():
        trip = by_no.get(number)
        if trip is None:
            notes.append({"train_no": number, "note": NOT_LOADABLE.get(number, "not loaded")})
            continue
        picked.append(trip)
        notes.append({"train_no": number, "note": reason})

    # State the pilots that could NOT be included, so their absence is visible
    # rather than silently replaced by a different train.
    for number, reason in NOT_LOADABLE.items():
        if number not in CHOSEN and number not in by_no:
            notes.append({"train_no": number, "note": reason})
    return picked, notes


def build() -> tuple[str, dict]:
    snapshot = load()
    # The replay deliberately shows everything it can, with flags, so the page is
    # an inspection tool rather than the production default view.
    policy = Policy(show_fakultatif=True, geometry_policy="allow_fallback")

    trips, notes = pick_trips(snapshot)

    meta = [
        {
            "trip_id": trip.trip_id,
            "train_no": trip.train_no,
            "status": trip.geometry_status,
            "class": trip.service_class,
            "coarse": trip.has_untimed_markers,
            "bypassed": trip.has_bypassed_waypoints,
            "book": trip.book,
            "length_km": round(trip.total_length_m / 1000.0, 1),
        }
        for trip in trips
    ]

    # Precompute legs ONCE per trip; _position_for is pure and cheap afterwards.
    legs = {trip.trip_id: _legs(trip, policy) for trip in trips}

    frames: list[list[dict]] = []
    for second in range(0, 86400, STEP_S):
        elapsed = float(second)
        row = []
        for index, trip in enumerate(trips):
            if not (trip.first_abs <= elapsed <= trip.last_abs):
                continue
            position = _position_for(trip, legs[trip.trip_id], elapsed, policy)
            if position is None:
                continue
            row.append(
                {
                    "i": index,
                    "lat": round(position.lat, 5),
                    "lon": round(position.lon, 5),
                    "s": position.status,
                    "f": position.from_code,
                    "t": position.to_code,
                    "n": position.next_stop_code,
                    "nt": position.next_stop_time,
                    "k": round(position.speed_kmh, 1),
                }
            )
        frames.append(row)

    # Printed vs engine, per pilot trip that is actually loaded.
    checks = []
    for trip in trips:
        for waypoint in trip.waypoints:
            if waypoint.stop_type != "stop" or waypoint.arrive_sod is None:
                continue
            elapsed = float(waypoint.arrive_abs)
            if not (0 <= elapsed < 86400):
                continue
            position = _position_for(trip, legs[trip.trip_id], elapsed, policy)
            checks.append(
                {
                    "train_no": trip.train_no,
                    "seq": waypoint.seq,
                    "station": waypoint.station_code,
                    "printed": (
                        f"{waypoint.arrive_sod // 3600:02d}:"
                        f"{(waypoint.arrive_sod % 3600) // 60:02d}:"
                        f"{waypoint.arrive_sod % 60:02d}"
                    ),
                    "engine_status": position.status if position else None,
                    "engine_s_m": round(position.s_m, 1) if position else None,
                    "expected_s_m": round(waypoint.s_m, 1),
                }
            )

    payload = {
        "step_s": STEP_S,
        "date": SWEEP_DATE.isoformat(),
        "trips": meta,
        "notes": notes,
        "frames": frames,
        "checks": checks,
    }
    html = _TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    return html, payload


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Engine replay - Gapeka 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
 body{margin:0;font-family:-apple-system,system-ui,sans-serif}
 #banner{background:#b00020;color:#fff;padding:8px 12px;font-weight:600;font-size:13px}
 #map{height:58vh}
 #bar{padding:8px 12px;display:flex;gap:12px;align-items:center;font-size:13px;flex-wrap:wrap}
 #panel{padding:8px 12px;max-height:26vh;overflow:auto;font-size:12px}
 table{border-collapse:collapse;margin-top:6px}
 td,th{border:1px solid #ccc;padding:2px 6px;text-align:left}
 th{background:#f4f4f4}
 .warn{color:#b00020}
 .key{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:4px}
</style></head><body>
<div id="banner">Estimated positions from the Gapeka schedule (assumes on-time, assumed daily)</div>
<div id="bar">
 <button id="play">Play</button>
 <input id="slider" type="range" min="0" max="0" value="0" style="flex:1;min-width:180px">
 <span id="clock">--:--</span>
 <label>speed <select id="speed">
   <option>1</option><option selected>4</option><option>12</option><option>40</option>
 </select></label>
</div>
<div id="map"></div>
<div id="panel"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const DATA = __DATA__;
const map = L.map('map').setView([-7.2,110.4],7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,
 attribution:'&copy; OpenStreetMap contributors (ODbL)'}).addTo(map);
const COLOURS=['#1565c0','#6a1b9a','#00695c','#ef6c00','#283593',
               '#ad1457','#00838f','#4e342e','#37474f'];
const markers = DATA.trips.map((t,i)=>{
  const m=L.circleMarker([-7.2,110.4],{radius:6,color:COLOURS[i%COLOURS.length],
    fillColor:COLOURS[i%COLOURS.length],fillOpacity:0.9,weight:2}).addTo(map);
  return m;
});
const slider=document.getElementById('slider'); slider.max=DATA.frames.length-1;
const clock=document.getElementById('clock'); let idx=0,timer=null;
function fmt(s){const h=Math.floor(s/3600),m=Math.floor(s%3600/60);
  return String(h).padStart(2,'0')+':'+String(m).padStart(2,'0');}
function render(){
  const row=DATA.frames[idx]||[];
  markers.forEach(m=>m.setStyle({opacity:0.12,fillOpacity:0.12}));
  row.forEach(p=>{
    const m=markers[p.i];
    m.setLatLng([p.lat,p.lon]).setStyle({opacity:1,fillOpacity:0.95});
    const t=DATA.trips[p.i];
    m.setPopupContent(`<b>KA ${t.train_no}</b> (${t.class}, book ${t.book})<br>`+
      `<b>${p.s}</b><br>${p.f} &rarr; ${p.t}<br>`+
      `next stop ${p.n||'-'} ${p.nt||''}<br>${p.k} km/h<br>`+
      `geometry ${t.status}${t.bypassed?' (bypassed waypoint)':''}`+
      (t.coarse?'<br><i>coarser estimate</i>':''));
  });
  clock.textContent=fmt(idx*DATA.step_s);
}
slider.oninput=()=>{idx=+slider.value;render();};
document.getElementById('play').onclick=e=>{
  if(timer){clearInterval(timer);timer=null;e.target.textContent='Play';return;}
  e.target.textContent='Pause';
  const speed=+document.getElementById('speed').value;
  timer=setInterval(()=>{idx=(idx+speed)%DATA.frames.length;slider.value=idx;render();},250);
};
render();

const legend = DATA.trips.map((t,i)=>`<span style="margin-right:12px">`+
  `<span class="key" style="background:${COLOURS[i%COLOURS.length]}"></span>`+
  `KA ${t.train_no} (${t.status}${t.bypassed?', bypass':''}, ${t.length_km} km)</span>`).join('');
const notes = DATA.notes.map(n=>`<li>KA ${n.train_no}: ${n.note}</li>`).join('');
const rows = DATA.checks.map(c=>`<tr><td>${c.train_no}</td><td>${c.seq}</td>`+
  `<td>${c.station}</td><td>${c.printed}</td><td>${c.engine_status}</td>`+
  `<td>${c.engine_s_m}</td><td>${c.expected_s_m}</td></tr>`).join('');
document.getElementById('panel').innerHTML =
  `<div><b>Trains on this page</b> (${DATA.date}, ${DATA.step_s} s frames)</div>`+
  `<div>${legend}</div>`+
  `<div style="margin-top:6px"><b>Selection notes</b>`+
  `<ul style="margin:4px 0 0 18px">${notes}</ul></div>`+
  `<div style="margin-top:8px"><b>Printed arrival vs engine status at that instant</b>`+
  ` (${DATA.checks.length} printed stops)</div>`+
  `<table><tr><th>KA</th><th>seq</th><th>station</th><th>printed arrive</th>`+
  `<th>engine status</th><th>engine s_m</th><th>expected s_m</th></tr>${rows}</table>`;
</script></body></html>
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html, payload = build()
    size = len(html.encode("utf-8"))
    OUT.write_text(html, encoding="utf-8")
    print(
        f"wrote {OUT} ({size / 1e6:.2f} MB, {len(payload['frames'])} frames, "
        f"{len(payload['trips'])} trips, {len(payload['checks'])} printed stops)"
    )
    for note in payload["notes"]:
        print(f"  KA {note['train_no']}: {note['note']}")
    if size > MAX_BYTES:
        print("WARNING: file exceeds 15 MB")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
