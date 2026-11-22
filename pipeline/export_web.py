"""B1: export the schedule for the static web app.

Writes ``web/public/data/`` (gitignored) with a compact, deterministic payload:

- ``manifest.json``  — version, effective date, policy defaults, counts, attribution
- ``stations.json``  — code, official name, lat, lon
- ``segments.json``  — unique polylines, polyline-encoded at precision 6, length_m
- ``trips.json``     — columnar integer arrays per trip, referring to segment ids

No timestamps, no Python object ids, sorted everywhere: two runs produce
byte-identical files. Files also carry a content-hashed alias so a browser can
cache-bust without a build step.

Trips with ``has_unmeasured`` are never exported. Fakultatif trips ARE exported
and flagged ``hidden_by_default`` so the UI can show them behind a toggle.

Usage:
    python -m pipeline.export_web
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from engine.model import Policy
from engine.snapshot import load
from pipeline import station_aliases

OUT = Path("web/public/data")
DB = Path("data/gapeka.db")
SCHEMA_VERSION = 1
POLYLINE_PRECISION = 6

STOP_TYPES = ("stop", "pass", "unknown_untimed")
CLASSES = ("reguler", "fakultatif", "unknown")

FLAG_COARSE = 1
FLAG_BYPASSED = 2
FLAG_STRAIGHT_LINE = 4


def encode_polyline(points: list[tuple[float, float]], precision: int = POLYLINE_PRECISION) -> str:
    """Google polyline encoding, scaled to ``precision`` decimal places."""
    factor = 10**precision
    last_lat = last_lon = 0
    out: list[str] = []

    def encode_value(value: int) -> str:
        value = ~(value << 1) if value < 0 else (value << 1)
        chunks = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    for lat, lon in points:
        ilat = round(lat * factor)
        ilon = round(lon * factor)
        out.append(encode_value(ilat - last_lat))
        out.append(encode_value(ilon - last_lon))
        last_lat, last_lon = ilat, ilon
    return "".join(out)


def _read_stations() -> dict[str, dict]:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT code, name, official_name, lat, lon FROM stations"
        ).fetchall()
    finally:
        connection.close()
    aliases = station_aliases.load()
    out = {}
    for code, name, official, lat, lon in rows:
        entry = aliases.get(code, {})
        out[code] = {
            "code": code,
            "official_name": official or entry.get("official_name") or name,
            "disambiguator": entry.get("disambiguator"),
            "lat": lat,
            "lon": lon,
        }
    return out


def build_payload() -> dict:
    snapshot = load()
    # The export is policy-independent: it contains every showable trip and lets
    # the UI apply `hidden_by_default`. No Policy is used here on purpose.
    stations = _read_stations()
    by_code = {code: index for index, code in enumerate(sorted(stations))}

    # --- unique segments ---------------------------------------------------
    segment_index: dict[tuple[tuple[float, float], ...], int] = {}
    segments: list[dict] = []

    def segment_id(segment) -> int:
        key = tuple(segment.coordinates)
        if key not in segment_index:
            points = [(lat, lon) for lat, lon in segment.coordinates]
            segment_index[key] = len(segments)
            segments.append(
                {
                    "from": segment.from_code,
                    "to": segment.to_code,
                    "length_m": round(segment.length_m, 1),
                    "quality": segment.quality,
                    "polyline": encode_polyline(points),
                    "points": len(points),
                }
            )
        return segment_index[key]

    trips: list[dict] = []
    for trip in snapshot.trips:
        if trip.geometry_status not in ("complete", "complete_estimated"):
            continue  # never export has_unmeasured / has_fallback

        segment_ids: list[int] = []
        reversed_flags: list[int] = []
        for segment in trip.segments:
            sid = segment_id(segment)
            canonical = segments[sid]
            reversed_flags.append(
                1
                if (canonical["from"], canonical["to"]) != (segment.from_code, segment.to_code)
                else 0
            )
            segment_ids.append(sid)

        flags = 0
        if trip.has_untimed_markers:
            flags |= FLAG_COARSE
        if trip.has_bypassed_waypoints:
            flags |= FLAG_BYPASSED
        if trip.has_straight_line_segment:
            flags |= FLAG_STRAIGHT_LINE

        rows = {
            "code": [by_code.get(w.station_code, -1) for w in trip.waypoints],
            "s_m": [round(w.s_m, 1) for w in trip.waypoints],
            "arrive": [-1 if w.arrive_abs is None else int(w.arrive_abs) for w in trip.waypoints],
            "depart": [-1 if w.depart_abs is None else int(w.depart_abs) for w in trip.waypoints],
            "stop_type": [STOP_TYPES.index(w.stop_type) for w in trip.waypoints],
        }

        trips.append(
            {
                "trip_id": trip.trip_id,
                "train_no": trip.train_no,
                "name": trip.name or "",
                "relation": "",
                "service_class": trip.service_class if trip.service_class in CLASSES else "unknown",
                "status": trip.geometry_status,
                "flags": flags,
                "hidden_by_default": trip.service_class != "reguler",
                "first_s": int(trip.first_abs),
                "last_s": int(trip.last_abs),
                "length_m": round(trip.total_length_m, 1),
                "segment_ids": segment_ids,
                "reversed": reversed_flags,
                "waypoints": rows,
            }
        )

    # relation comes from the DB (trips.relation), so the panel can show it.
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        relations = {
            row[0]: row[1] for row in connection.execute("SELECT trip_id, relation FROM trips")
        }
        names = {
            row[0]: (row[1], row[2])
            for row in connection.execute("SELECT trip_id, train_no, relation FROM trips")
        }
    finally:
        connection.close()
    for trip in trips:
        trip["relation"] = relations.get(trip["trip_id"], "") or ""
        if not trip["name"] and trip["trip_id"] in names:
            trip["name"] = names[trip["trip_id"]][0] or ""

    return {
        "stations": stations,
        "segments": segments,
        "trips": trips,
        "snapshot": snapshot,
    }


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def export(out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    snapshot = payload["snapshot"]

    stations = {
        "schema": SCHEMA_VERSION,
        "stations": [payload["stations"][code] for code in sorted(payload["stations"])],
    }
    segments = {
        "schema": SCHEMA_VERSION,
        "precision": POLYLINE_PRECISION,
        "segments": payload["segments"],
    }
    trips = {
        "schema": SCHEMA_VERSION,
        "stop_types": list(STOP_TYPES),
        "trips": payload["trips"],
    }

    contents: dict[str, bytes] = {}
    for name, data in (("stations", stations), ("segments", segments), ("trips", trips)):
        contents[name] = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()

    combined = hashlib.sha256()
    for name in sorted(contents):
        combined.update(contents[name])
    content_hash = combined.hexdigest()[:16]

    attribution = {
        "osm": "© OpenStreetMap contributors",
        "osm_url": "https://www.openstreetmap.org/copyright",
        "disclaimer": (
            "Posisi estimasi berdasarkan jadwal Gapeka 2026, bukan posisi aktual. "
            "Diasumsikan tepat waktu dan beroperasi setiap hari."
        ),
        "preview_banner": ("Preview Gapeka 2026 (berlaku resmi mulai 1 Desember 2026)"),
    }

    manifest = {
        "schema": SCHEMA_VERSION,
        "version_name": snapshot.version_name,
        "effective_from": snapshot.effective_from,
        "effective_to": snapshot.effective_to,
        "policy": Policy().as_dict(),
        "content_hash": content_hash,
        "max_day_offset": snapshot.max_day_offset,
        "counts": {
            "stations": len(stations["stations"]),
            "segments": len(segments["segments"]),
            "trips": len(trips["trips"]),
        },
        "attribution": attribution,
        "files": {},
    }

    for name, body in contents.items():
        filename = f"{name}.{_hash(body)}.json"
        (out / filename).write_bytes(body)
        # A stable alias too: the UI can load `trips.json` and cache-bust by hash.
        (out / f"{name}.json").write_bytes(body)
        manifest["files"][name] = filename

    for name, body in contents.items():
        (out / f"{name}.json").write_bytes(body)

    manifest_body = json.dumps(manifest, indent=1, sort_keys=True).encode()
    (out / "manifest.json").write_bytes(manifest_body)

    sizes = {}
    for name, body in contents.items():
        sizes[name] = {
            "raw": len(body),
            "gzip": len(gzip.compress(body, 9)),
        }
    sizes["manifest"] = {"raw": len(manifest_body), "gzip": len(gzip.compress(manifest_body, 9))}
    sizes["total"] = {
        "raw": sum(item["raw"] for item in sizes.values()),
        "gzip": sum(item["gzip"] for item in sizes.values()),
    }

    summary = {
        "content_hash": content_hash,
        "max_day_offset": snapshot.max_day_offset,
        "manifest": manifest,
        "sizes": sizes,
        "trips": len(trips["trips"]),
        "segments": len(segments["segments"]),
        "stations": len(stations["stations"]),
    }
    (Path("data/review") / "web_export.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    summary = export()
    sizes = summary["sizes"]
    print(f"wrote {OUT} (content hash {summary['content_hash']})")
    print(
        f"  stations {summary['stations']}, segments {summary['segments']}, "
        f"trips {summary['trips']}"
    )
    for name, size in sizes.items():
        print(f"  {name:9s} raw {size['raw'] / 1024:8.1f} kB   gzip {size['gzip'] / 1024:8.1f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
