"""Station coordinates from external sources only (Phase 3a step 4b).

Sources are tried in order: **Wikidata** first, then **OpenStreetMap**. Every
coordinate row records where it came from, how it was matched, and when it was
retrieved. Ambiguous or multiple candidates are NOT resolved here — they go to a
review list (Hard Rule 1: never guess).

Downloaded payloads are cached under ``data/external/`` (gitignored) with a
manifest of source + retrieval date.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "live-gapeka/0.1 (offline timetable pipeline)"

EXTERNAL_DIR = Path("data/external")
CACHE_WIKIDATA = EXTERNAL_DIR / "wikidata_stations.json"
CACHE_OSM = EXTERNAL_DIR / "osm_stations.json"
MANIFEST = EXTERNAL_DIR / "manifest.json"

# Java bounding box, used only for sanity reporting.
JAVA_BBOX = {"min_lat": -9.0, "max_lat": -5.5, "min_lon": 105.0, "max_lon": 115.0}

# Wikidata: Indonesian railway stations carry P296 (station code) and P625 (coords).
WIKIDATA_QUERY = """
SELECT ?item ?code ?coord ?label WHERE {
  ?item wdt:P31/wdt:P279* wd:Q55488 .
  ?item wdt:P17 wd:Q252 .
  ?item wdt:P296 ?code .
  OPTIONAL { ?item wdt:P625 ?coord . }
  OPTIONAL { ?item rdfs:label ?label FILTER(LANG(?label) = "id") }
}
"""


@dataclass
class Candidate:
    source: str
    source_id: str
    name: str
    lat: float
    lon: float
    code: str | None = None


def _http(url: str, *, data: bytes | None = None, accept: str = "application/json") -> str:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8")


def _record_manifest(entry: dict) -> None:
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest = [item for item in manifest if item["path"] != entry["path"]]
    manifest.append(entry)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def fetch_wikidata(force: bool = False) -> list[dict]:
    """Fetch Indonesian station items with a code and coordinates from Wikidata."""
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_WIKIDATA.exists() and not force:
        return json.loads(CACHE_WIKIDATA.read_text(encoding="utf-8"))

    body = urllib.parse.urlencode({"query": WIKIDATA_QUERY, "format": "json"}).encode()
    raw = json.loads(_http(WIKIDATA_ENDPOINT, data=body))
    rows = raw["results"]["bindings"]
    CACHE_WIKIDATA.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    _record_manifest(
        {
            "path": str(CACHE_WIKIDATA),
            "source": "wikidata",
            "url": WIKIDATA_ENDPOINT,
            "license": "CC0",
            "retrieved": date.today().isoformat(),
            "rows": len(rows),
        }
    )
    return rows


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    """Parse a Wikidata ``Point(lon lat)`` literal."""
    if not wkt or not wkt.startswith("Point("):
        return None
    try:
        lon, lat = wkt[6:-1].split()
        return float(lat), float(lon)
    except (ValueError, IndexError):
        return None


def wikidata_by_code(rows: list[dict]) -> dict[str, list[Candidate]]:
    """Group Wikidata candidates by station code."""
    by_code: dict[str, list[Candidate]] = {}
    for row in rows:
        code = row.get("code", {}).get("value")
        point = parse_point(row.get("coord", {}).get("value"))
        if not code or point is None:
            continue
        lat, lon = point
        by_code.setdefault(code.upper(), []).append(
            Candidate(
                source="wikidata",
                source_id=row["item"]["value"].rsplit("/", 1)[-1],
                name=row.get("label", {}).get("value", ""),
                lat=lat,
                lon=lon,
                code=code,
            )
        )
    return by_code


def fetch_osm(names: list[str], force: bool = False) -> list[dict]:
    """Fetch Indonesian railway stations from Overpass, limited to given names."""
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_OSM.exists() and not force:
        return json.loads(CACHE_OSM.read_text(encoding="utf-8"))

    # Query by railway=station/halt within Java, then match locally by name.
    query = (
        "[out:json][timeout:120];"
        'area["name"="Jawa"]["type"="boundary"]->.java;'
        'node["railway"~"^(station|halt)$"](area.java);'
        "out tags center;"
    )
    rows = []
    for attempt in range(3):
        try:
            raw = json.loads(
                _http(OVERPASS_ENDPOINT, data=urllib.parse.urlencode({"data": query}).encode())
            )
            rows = raw.get("elements", [])
            break
        except Exception:  # noqa: BLE001 - transient network
            if attempt == 2:
                raise
            time.sleep(20)

    CACHE_OSM.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    _record_manifest(
        {
            "path": str(CACHE_OSM),
            "source": "osm",
            "url": OVERPASS_ENDPOINT,
            "license": "ODbL (attribution required)",
            "retrieved": date.today().isoformat(),
            "rows": len(rows),
        }
    )
    return rows


def normalise_name(text: str) -> str:
    return " ".join(text.upper().replace(".", " ").replace("-", " ").split())


def osm_candidates(rows: list[dict]) -> dict[str, list[Candidate]]:
    """Index OSM stations by normalised name."""
    by_name: dict[str, list[Candidate]] = {}
    for row in rows:
        tags = row.get("tags", {})
        name = tags.get("name")
        if not name or row.get("lat") is None:
            continue
        by_name.setdefault(normalise_name(name), []).append(
            Candidate(
                source="osm",
                source_id=f"{row['type']}/{row['id']}",
                name=name,
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                code=tags.get("ref"),
            )
        )
    return by_name


def wikidata_by_name(rows: list[dict]) -> dict[str, list[Candidate]]:
    """Index Wikidata candidates by normalised label, keeping only those with coords."""
    by_name: dict[str, list[Candidate]] = {}
    for row in rows:
        label = row.get("label", {}).get("value")
        point = parse_point(row.get("coord", {}).get("value"))
        if not label or point is None:
            continue
        lat, lon = point
        by_name.setdefault(normalise_name(label), []).append(
            Candidate(
                source="wikidata",
                source_id=row["item"]["value"].rsplit("/", 1)[-1],
                name=label,
                lat=lat,
                lon=lon,
                code=row.get("code", {}).get("value"),
            )
        )
    return by_name
