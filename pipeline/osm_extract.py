"""Extract the Java rail graph and stations from the Geofabrik PBF.

**Memory-lean by design.** An earlier version called ``apply_file(locations=True)``
which makes pyosmium build a coordinate index for *every* node in Java; that needs
tens of GB and thrashed the machine. Here the work is split into two streaming
passes with no location index at all:

1. **ways pass** — keep only routable ``railway=rail`` ways and collect the IDs of
   the nodes they reference (8.9k ways, ~52k node IDs, ~190 MB peak).
2. **nodes pass** — read every node and keep coordinates only for those IDs, in
   compact ``array`` storage, plus every ``railway=station|halt`` node.

Both passes use ``locations=False``: node coordinates come from the node callback,
which is all we need.

Source choice: the **Geofabrik Java extract**, not an Overpass query, because
Overpass returned 502/504 repeatedly during this run and the extract is a stable
snapshot we can hash. Licence: ODbL 1.0, © OpenStreetMap contributors.

Usage:
    python -m pipeline.osm_extract
"""

from __future__ import annotations

import hashlib
import json
import pickle
import time
from array import array
from datetime import date
from pathlib import Path

import osmium

PBF = Path("data/external/java-latest.osm.pbf")
OUT = Path("data/external/java_rail_graph.json")
MANIFEST = Path("data/external/manifest.json")

EXCLUDED_RAILWAY = {
    "abandoned",
    "disused",
    "construction",
    "proposed",
    "razed",
    "preserved",
    "light_rail",
    "subway",
    "tram",
    "narrow_gauge",
    "monorail",
    "funicular",
}
EXCLUDED_SERVICE = {"yard", "siding", "spur", "crossover", "parking_aisle"}


class WaysPass(osmium.SimpleHandler):
    """Pass 1: routable ways and the node IDs they use."""

    def __init__(self) -> None:
        super().__init__()
        self.ways: list[dict] = []
        self.node_ids: set[int] = set()

    def way(self, w) -> None:
        tags = {tag.k: tag.v for tag in w.tags}
        railway = tags.get("railway")
        # ALLOWLIST, not a blocklist: only real track may enter the routing graph.
        # A blocklist let railway=platform (1,074 ways) in, which fragmented the
        # network into ~1,150 components and made most routes unreachable.
        if railway != "rail":
            return
        if tags.get("service") in EXCLUDED_SERVICE:
            return
        nodes = [node.ref for node in w.nodes]
        if len(nodes) < 2:
            return
        self.ways.append(
            {
                "id": w.id,
                "nodes": nodes,
                "railway": railway,
                "service": tags.get("service"),
                "name": tags.get("name"),
                "maxspeed": tags.get("maxspeed"),
            }
        )
        self.node_ids.update(nodes)


class NodesPass(osmium.SimpleHandler):
    """Pass 2: coordinates for the needed node IDs, plus station nodes."""

    def __init__(self, needed: set[int]) -> None:
        super().__init__()
        self.needed = needed
        self.ids = array("q")
        self.lat = array("f")
        self.lon = array("f")
        self.stations: list[dict] = []

    def node(self, n) -> None:
        # HOT PATH: this callback runs once per node in Java (~142 million).
        # Membership is checked before any tag work, and a tag dict is only built
        # for nodes we actually keep. Building a dict unconditionally made this
        # pass take over 10 minutes instead of ~2.
        nid = n.id
        wanted = nid in self.needed
        if not wanted and not n.tags:
            return
        tags = None
        if not wanted:
            for tag in n.tags:
                if tag.k == "railway" and tag.v in ("station", "halt"):
                    tags = {t.k: t.v for t in n.tags}
                    break
            if tags is None:
                return
        else:
            tags = {tag.k: tag.v for tag in n.tags}

        if tags.get("railway") in ("station", "halt"):
            self.stations.append(
                {
                    "id": n.id,
                    "lat": float(n.location.lat),
                    "lon": float(n.location.lon),
                    "name": tags.get("name"),
                    "ref": tags.get("ref"),
                    "railway": tags["railway"],
                }
            )
        if n.id in self.needed:
            self.ids.append(n.id)
            self.lat.append(n.location.lat)
            self.lon.append(n.location.lon)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_manifest(entry: dict) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    manifest = [item for item in manifest if item["path"] != entry["path"]]
    manifest.append(entry)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(cache_dir: Path = Path("/tmp")) -> int:
    if not PBF.exists():
        print(f"error: {PBF} missing; see docs/DATA_SOURCES.md")
        return 2

    started = time.time()

    pass1_cache = cache_dir / "gapeka_osm_ways.pkl"
    if pass1_cache.exists():
        print("pass 1: reusing cached ways")
        with pass1_cache.open("rb") as handle:
            pass1 = pickle.load(handle)
        ways, node_ids = pass1["ways"], pass1["node_ids"]
    else:
        print("pass 1: ways ...")
        ways_pass = WaysPass()
        ways_pass.apply_file(str(PBF), locations=False)
        ways, node_ids = ways_pass.ways, ways_pass.node_ids
        with pass1_cache.open("wb") as handle:
            pickle.dump({"ways": ways, "node_ids": node_ids}, handle)
        print(
            f"pass 1: {len(ways):,} ways, {len(node_ids):,} node ids ({time.time() - started:.0f}s)"
        )

    print("pass 2: nodes ...")
    nodes_pass = NodesPass(node_ids)
    nodes_pass.apply_file(str(PBF), locations=False)
    print(
        f"pass 2: {len(nodes_pass.ids):,} coords, "
        f"{len(nodes_pass.stations):,} stations ({time.time() - started:.0f}s)"
    )

    coords = [
        {"id": int(node_id), "lat": float(lat), "lon": float(lon)}
        for node_id, lat, lon in zip(nodes_pass.ids, nodes_pass.lat, nodes_pass.lon, strict=True)
    ]
    coord_index = {item["id"] for item in coords}
    usable = [w for w in ways if all(n in coord_index for n in w["nodes"])]

    payload = {
        "source": "Geofabrik Java extract",
        "retrieved": date.today().isoformat(),
        "pbf_sha256": sha256_of(PBF),
        "license": "ODbL 1.0, © OpenStreetMap contributors",
        "ways": usable,
        "stations": nodes_pass.stations,
        "node_coords": coords,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    record_manifest(
        {
            "path": str(OUT),
            "source": "geofabrik_java",
            "url": "https://download.geofabrik.de/asia/indonesia/java/",
            "pbf_sha256": payload["pbf_sha256"],
            "license": "ODbL 1.0, © OpenStreetMap contributors",
            "retrieved": payload["retrieved"],
            "ways": len(usable),
            "stations": len(nodes_pass.stations),
            "nodes": len(coords),
        }
    )

    print(f"ways usable: {len(usable):,}")
    print(f"output: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    print(f"runtime: {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
