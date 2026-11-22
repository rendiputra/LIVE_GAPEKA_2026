"""R2 (Phase 5b): self-contained Leaflet replay page for the position engine.

Frames come from the PUBLIC ``positions_at()`` over a 30-hour window
(2026-12-01 00:00 -> 2026-12-02 06:00 WIB, 30 s step), so trips that started on
the previous service date and trips with ``day_offset >= 1`` are both visible.
An earlier version looped ``range(0, 86400)`` and called the private
``_position_for`` with a single service-date elapsed, which silently cut every
midnight tail.

The page draws each trip's routed polyline and its stations, and includes a
REPRODUCTION check (not independent validation): at every row that has a printed
time, the engine's ``s(t)`` must equal that row's cumulative distance within 1 m.

Usage:
    python -m pipeline.engine_replay
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.model import Policy
from engine.position import positions_at
from engine.snapshot import load

OUT = Path("data/review/engine_replay.html")
DB = Path("data/gapeka.db")
WIB = ZoneInfo("Asia/Jakarta")

START_DATE = date(2026, 12, 1)
WINDOW_HOURS = 30
STEP_S = 30
MAX_BYTES = 15 * 1024 * 1024
S_M_TOLERANCE_M = 1.0

# train_no -> why it is on the page
# Why each train is on the page. These reasons describe the SELECTION, never the
# current status: the status is appended from the loaded trip, so a note can
# never contradict the data again.
CHOSEN: dict[str, str] = {
    "249": "pilot; only reachable after the H6 SRI override",
    "250": "pilot; same route as KA 249 in the other direction",
    "259F": "pilot; fakultatif, so it tests the shown/hidden policy",
    "260F": "pilot; crosses midnight, so it tests day_offset",
    "265": "chosen for the BTT/CS junction area",
    "351": "Book 2; exercises a bypassed waypoint",
    "13": "Book 1; one of the longest trips",
    "436": "Book 2; a short regional service",
    "183": "Book 1; a long service",
}

# The replay shows everything it can, with flags: it is an inspection tool, not
# the production default view.
REPLAY_POLICY = Policy(show_fakultatif=True, geometry_policy="allow_fallback")


def stations_from_db() -> dict[str, dict]:
    if not DB.exists():
        return {}
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return {
            row[0]: {
                "name": row[1],
                "official_name": row[2] or row[1],
                "lat": row[3],
                "lon": row[4],
            }
            for row in connection.execute(
                "SELECT code, name, official_name, lat, lon FROM stations"
            )
            if row[3] is not None and row[4] is not None
        }
    finally:
        connection.close()


def pick_trips(snapshot) -> tuple[list, list[dict]]:
    by_no: dict[str, object] = {}
    for trip in snapshot.trips:
        by_no.setdefault(trip.train_no, trip)

    picked, notes = [], []
    for number, reason in CHOSEN.items():
        trip = by_no.get(number)
        if trip is None:
            notes.append({"train_no": number, "note": "not loaded"})
            continue
        picked.append(trip)
        notes.append(
            {
                "train_no": number,
                "note": f"{reason} [status={trip.geometry_status}, class={trip.service_class}]",
            }
        )
    return picked, notes


def clock_text(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%d %H:%M")


def build() -> tuple[str, dict]:
    snapshot = load()
    policy = REPLAY_POLICY
    start = datetime(START_DATE.year, START_DATE.month, START_DATE.day, tzinfo=WIB)
    total_seconds = WINDOW_HOURS * 3600

    trips, notes = pick_trips(snapshot)
    index_of = {trip.trip_id: position for position, trip in enumerate(trips)}

    meta = []
    routes = []
    trip_stations = []
    for trip in trips:
        meta.append(
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
        )
        route = []
        for segment in trip.segments:
            for lat, lon in segment.coordinates:
                point = [round(lat, 5), round(lon, 5)]
                if not route or route[-1] != point:
                    route.append(point)
        routes.append(route)
        trip_stations.append(
            [
                {
                    "code": waypoint.station_code,
                    "s": round(waypoint.s_m, 1),
                    "type": waypoint.stop_type,
                    "arr": waypoint.arrive_sod,
                    "dep": waypoint.depart_sod,
                }
                for waypoint in trip.waypoints
            ]
        )

    frames: list[list[dict]] = []
    clocks: list[str] = []
    for second in range(0, total_seconds + 1, STEP_S):
        instant = start + timedelta(seconds=second)
        clocks.append(clock_text(instant))
        row = []
        for position in positions_at(snapshot, instant, policy):
            index = index_of.get(position.trip_id)
            if index is None:
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

    checks = reproduction_check(snapshot, policy)

    payload = {
        "step_s": STEP_S,
        "window_hours": WINDOW_HOURS,
        "date": START_DATE.isoformat(),
        "clocks": clocks,
        "trips": meta,
        "routes": routes,
        "trip_stations": trip_stations,
        "stations": stations_from_db(),
        "notes": notes,
        "frames": frames,
        "check": checks,
    }
    html = _TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    return html, payload


def reproduction_check(snapshot, policy: Policy) -> dict:
    """At every printed time, does the engine sit at that row's distance?

    This is a REPRODUCTION check, not independent validation: the engine is built
    from the same printed times, so agreement proves the loader, the cumulative
    distances and the motion profile are mutually consistent, and nothing more.
    """
    start = datetime(START_DATE.year, START_DATE.month, START_DATE.day, tzinfo=WIB)
    results = {"policies": []}

    for label, active_policy in (
        ("default", Policy()),
        ("show_fakultatif", Policy(show_fakultatif=True)),
        ("show_fakultatif+allow_fallback", REPLAY_POLICY),
    ):
        checked = 0
        mismatches = []
        absent = []
        trips_checked = 0
        staggered_trips: set[str] = set()

        for trip in snapshot.trips:
            if not trip.is_visible(active_policy):
                continue
            if trip.service_class != "reguler" and not active_policy.show_fakultatif:
                continue
            if trip.geometry_status == "has_unmeasured":
                continue
            trips_checked += 1
            # A stop that arrives before midnight and departs after it cannot be
            # represented by ONE day_offset per row. The parser gives the row
            # day_offset=1, which pushes the ARRIVAL a day late. Counting these
            # rows separately keeps the mismatch total honest.
            if any(
                w.arrive_sod is not None
                and w.depart_sod is not None
                and w.arrive_sod > w.depart_sod
                for w in trip.waypoints
            ):
                staggered_trips.add(trip.trip_id)

            for waypoint in trip.waypoints:
                for kind, absolute in (
                    ("arrive", waypoint.arrive_abs),
                    ("depart", waypoint.depart_abs),
                ):
                    if absolute is None:
                        continue
                    # First row has arrive == depart; do not count it twice.
                    if kind == "depart" and waypoint.arrive_abs == waypoint.depart_abs:
                        continue
                    instant = start + timedelta(seconds=absolute)
                    found = [
                        position
                        for position in positions_at(snapshot, instant, active_policy)
                        if position.trip_id == trip.trip_id
                    ]
                    checked += 1
                    if not found:
                        absent.append(
                            {
                                "trip_id": trip.trip_id,
                                "train_no": trip.train_no,
                                "station": waypoint.station_code,
                                "kind": kind,
                                "sod": absolute,
                            }
                        )
                        continue
                    delta = abs(found[0].s_m - waypoint.s_m)
                    if delta > S_M_TOLERANCE_M:
                        mismatches.append(
                            {
                                "trip_id": trip.trip_id,
                                "train_no": trip.train_no,
                                "station": waypoint.station_code,
                                "kind": kind,
                                "expected_m": round(waypoint.s_m, 2),
                                "engine_m": round(found[0].s_m, 2),
                                "delta_m": round(delta, 2),
                                "cause": (
                                    "midnight_straddle_row"
                                    if trip.trip_id in staggered_trips
                                    else "unexplained"
                                ),
                            }
                        )

        by_cause: dict[str, int] = {}
        for row in mismatches:
            by_cause[row["cause"]] = by_cause.get(row["cause"], 0) + 1

        results["policies"].append(
            {
                "policy": label,
                "trips_checked": trips_checked,
                "printed_times_checked": checked,
                "mismatches": len(mismatches),
                "mismatches_by_cause": by_cause,
                "trips_with_midnight_straddle": len(staggered_trips),
                "absent": len(absent),
                "mismatch_examples": mismatches[:20],
                "absent_examples": absent[:20],
                "tolerance_m": S_M_TOLERANCE_M,
            }
        )

    results["note"] = (
        "Reproduction check, NOT independent validation. The engine is built from "
        "the same printed times, so agreement shows the loader, cumulative "
        "distances and motion profile are mutually consistent."
    )
    return results


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Engine replay - Gapeka 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
 body{margin:0;font-family:-apple-system,system-ui,sans-serif}
 #banner{background:#b00020;color:#fff;padding:8px 12px;font-weight:600;font-size:13px}
 #map{height:56vh}
 #bar{padding:8px 12px;display:flex;gap:12px;align-items:center;font-size:13px;flex-wrap:wrap}
 #panel{padding:8px 12px;max-height:34vh;overflow:auto;font-size:12px}
 table{border-collapse:collapse;margin-top:6px}
 td,th{border:1px solid #ccc;padding:2px 6px;text-align:left}
 th{background:#f4f4f4}
 .warn{color:#b00020;font-weight:600}
 .key{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:4px}
</style></head><body>
<div id="banner">Estimated positions from the Gapeka schedule (assumes on-time, assumed daily)</div>
<div id="bar">
 <button id="play">Play</button>
 <input id="slider" type="range" min="0" max="0" value="0" style="flex:1;min-width:160px">
 <span id="clock" style="font-variant-numeric:tabular-nums">--</span>
 <label>speed <select id="speed">
   <option>1</option><option selected>4</option><option>12</option><option>40</option>
 </select></label>
 <label>train <select id="tripSel"><option value="">-- pick a train --</option></select></label>
 <label><input type="checkbox" id="follow"> follow selected</label>
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

// Routes first, so markers stay on top.
const routeLayer = L.layerGroup().addTo(map);
DATA.routes.forEach((route,i)=>{
  if(route.length<2) return;
  L.polyline(route,{color:COLOURS[i%COLOURS.length],weight:2,opacity:0.45}).addTo(routeLayer);
});

// Stations: one marker per station on the selected trips, with printed times.
const stationLayer = L.layerGroup().addTo(map);
const stationIndex = {};
DATA.trips.forEach((t,i)=>{
  DATA.trip_stations[i].forEach(w=>{
    const info=DATA.stations[w.code];
    if(!info) return;
    const key=w.code+'|'+i;
    if(stationIndex[key]) return;
    stationIndex[key]=true;
    const fmt=v=>v==null?'-':String(Math.floor(v/3600)).padStart(2,'0')+':'+
      String(Math.floor(v%3600/60)).padStart(2,'0')+':'+String(v%60).padStart(2,'0');
    L.circleMarker([info.lat,info.lon],{radius:2.5,color:'#37474f',
      fillColor:'#37474f',fillOpacity:0.8,weight:1})
      .bindPopup(`<b>${w.code}</b> ${info.official_name||info.name}<br>`+
        `KA ${t.train_no} &middot; ${w.type}<br>`+
        `datang ${fmt(w.arr)}<br>berangkat ${fmt(w.dep)}`)
      .addTo(stationLayer);
  });
});

const markers = DATA.trips.map((t,i)=>{
  return L.circleMarker([-7.2,110.4],{radius:6,color:COLOURS[i%COLOURS.length],
    fillColor:COLOURS[i%COLOURS.length],fillOpacity:0.9,weight:2}).addTo(map);
});
const slider=document.getElementById('slider'); slider.max=DATA.frames.length-1;
// Dropdown: jumping to a trip's FIRST frame is how you find a train that is only
// on the map for a few minutes (e.g. KA 260F just after midnight).
const tripSel=document.getElementById('tripSel');
DATA.trips.forEach((t,i)=>{
  const o=document.createElement('option'); o.value=i;
  o.textContent=`KA ${t.train_no} (${t.status})`; tripSel.appendChild(o);
});
let selected=null;
function firstFrameOf(i){
  for(let f=0;f<DATA.frames.length;f++){
    if((DATA.frames[f]||[]).some(p=>p.i===i)) return f;
  }
  return -1;
}
tripSel.onchange=()=>{
  const v=tripSel.value;
  selected = v==='' ? null : +v;
  if(selected!==null){
    const f=firstFrameOf(selected);
    if(f>=0){ idx=f; slider.value=idx; }
    const m=markers[selected];
    if(m && m.getLatLng()) map.setView(m.getLatLng(), Math.max(map.getZoom(),9));
  }
  render();
};
const clock=document.getElementById('clock'); let idx=0,timer=null;
const follow=document.getElementById('follow');
function render(){
  const row=DATA.frames[idx]||[];
  if(follow.checked && selected!==null){
    const p=row.find(x=>x.i===selected);
    if(p){ map.panTo([p.lat,p.lon]); }
  }
  markers.forEach(m=>m.setStyle({opacity:0.10,fillOpacity:0.10}));
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
  clock.textContent=DATA.clocks[idx];
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
const checks = DATA.check.policies.map(c=>
  `<tr><td>${c.policy}</td><td>${c.trips_checked}</td><td>${c.printed_times_checked}</td>`+
  `<td class="${c.mismatches?'warn':''}">${c.mismatches}</td>`+
  `<td class="${c.absent?'warn':''}">${c.absent}</td><td>${c.tolerance_m} m</td></tr>`).join('');
const activeNow=(DATA.frames[idx]||[]).map(p=>{
  const t=DATA.trips[p.i];
  return `<li>KA ${t.train_no} &middot; ${p.s} &middot; ${p.f} &rarr; ${p.t}`+
    ` &middot; next ${p.n||'-'} ${p.nt||''} &middot; ${p.k} km/h</li>`;
}).join('') || '<li><i>no active trains at this instant</i></li>';
document.getElementById('panel').innerHTML =
  `<div><b>Window</b> ${DATA.date} + ${DATA.window_hours} h, ${DATA.step_s} s frames `+
  `(${DATA.frames.length} frames)</div>`+
  `<div style="margin-top:6px"><b>Trains on this page</b></div><div>${legend}</div>`+
  `<div style="margin-top:6px"><b>Selection notes</b>`+
  `<ul style="margin:4px 0 0 18px">${notes}</ul></div>`+
  `<div style="margin-top:8px"><b>Active now</b> (${(DATA.frames[idx]||[]).length})`+
  `<ul style="margin:4px 0 0 18px">${activeNow}</ul></div>`+
  `<div style="margin-top:8px"><b>Reproduction check</b> - `+
  `${DATA.check.note}</div>`+
  `<table><tr><th>policy</th><th>trips</th><th>printed times</th>`+
  `<th>s_m mismatches</th><th>absent</th><th>tolerance</th></tr>${checks}</table>`;
</script></body></html>
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html, payload = build()
    size = len(html.encode("utf-8"))
    OUT.write_text(html, encoding="utf-8")
    print(
        f"wrote {OUT} ({size / 1e6:.2f} MB, {len(payload['frames'])} frames, "
        f"{len(payload['trips'])} trips, {payload['window_hours']} h window)"
    )
    for note in payload["notes"]:
        print(f"  KA {note['train_no']}: {note['note']}")
    for row in payload["check"]["policies"]:
        print(
            f"  check[{row['policy']}]: trips {row['trips_checked']}, "
            f"printed times {row['printed_times_checked']}, "
            f"mismatches {row['mismatches']}, absent {row['absent']}"
        )
    if size > MAX_BYTES:
        print("WARNING: file exceeds 15 MB")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
