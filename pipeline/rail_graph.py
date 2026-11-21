"""Phase 4: build a routed rail graph from the OSM extract and snap stations.

Deterministic. No geometry is ever invented: a route is either found on real OSM
rail, or the segment is marked with a quality tier that says what happened.

Graph model
-----------
- nodes are OSM node IDs, edges are consecutive node pairs inside a way;
- an edge carries its length in metres (haversine on the two node coordinates);
- ways are undirected for routing: a trip using A->B reuses the B->A route
  reversed, so a pair is routed once.

Snapping
--------
A station is projected onto the nearest **edge** (not node), and the edge is split
at the projection so routed lengths stay accurate. Bands come from
``data/config/geometry.yaml``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EARTH_RADIUS_M = 6371008.8


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def project_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], float, float]:
    """Project a point onto a segment in a local metric plane.

    Returns ``(projected_point, distance_m, t)`` where ``t`` in [0,1] is the
    fraction along the segment. The plane is a small equirectangular approximation
    around the point, which is accurate enough at the kilometre scale and keeps the
    maths dependency-free.
    """
    lat0 = math.radians(point[0])
    cos_lat = math.cos(lat0)

    def to_xy(coord: tuple[float, float]) -> tuple[float, float]:
        return (
            math.radians(coord[1] - point[1]) * cos_lat * EARTH_RADIUS_M,
            math.radians(coord[0] - point[0]) * EARTH_RADIUS_M,
        )

    px, py = to_xy(point)
    ax, ay = to_xy(start)
    bx, by = to_xy(end)

    abx, aby = bx - ax, by - ay
    length_sq = abx * abx + aby * aby
    if length_sq == 0:
        t = 0.0
    else:
        t = ((px - ax) * abx + (py - ay) * aby) / length_sq
        t = max(0.0, min(1.0, t))

    proj_x = ax + t * abx
    proj_y = ay + t * aby
    distance = math.hypot(px - proj_x, py - proj_y)

    # Convert the projected point back to lat/lon.
    lon = point[1] + math.degrees(proj_x / (cos_lat * EARTH_RADIUS_M))
    lat = point[0] + math.degrees(proj_y / EARTH_RADIUS_M)
    return (lat, lon), distance, t


@dataclass
class Edge:
    """One graph edge: two OSM nodes and the length between them."""

    a: int
    b: int
    length_m: float
    way_id: int


def orient_geometry(segment: dict, from_code: str, to_code: str) -> list[list[float]]:
    """Return a segment's coordinates oriented from ``from_code`` to ``to_code``.

    Segments are stored once per undirected pair, keyed with ``from_code < to_code``.
    A hop travelling the other way MUST have its coordinates reversed, otherwise the
    concatenated trip polyline jumps back and forth between the two ends (observed:
    a 116.8 km trip drawn as 256.2 km).

    Ground truth is the segment's own ``from_code``: if it differs from the hop's
    origin, reverse.
    """
    coordinates = (segment.get("geometry") or {}).get("coordinates") or []
    if not coordinates:
        return []
    if segment["from_code"] == from_code:
        return coordinates
    return list(reversed(coordinates))


@dataclass
class SnapResult:
    """Where a station landed on the network."""

    code: str
    node_id: int | None
    lat: float | None
    lon: float | None
    snap_distance_m: float | None
    edge: tuple[int, int] | None
    band: str  # ok | review | rejected

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "node_id": self.node_id,
            "lat": self.lat,
            "lon": self.lon,
            "snap_distance_m": None
            if self.snap_distance_m is None
            else round(self.snap_distance_m, 1),
            "edge": None if self.edge is None else list(self.edge),
            "band": self.band,
        }


@dataclass
class RailGraph:
    """Adjacency structure over OSM rail nodes."""

    coords: dict[int, tuple[float, float]]
    adjacency: dict[int, list[Edge]] = field(default_factory=dict)
    way_of_edge: dict[tuple[int, int], int] = field(default_factory=dict)
    service_of_edge: dict[tuple[int, int], str] = field(default_factory=dict)

    @classmethod
    def from_ways(cls, ways: list[dict], coords: dict[int, tuple[float, float]]) -> RailGraph:
        graph = cls(coords=coords)
        for way in ways:
            nodes = way["nodes"]
            for a, b in zip(nodes, nodes[1:], strict=False):
                if a not in coords or b not in coords:
                    continue
                length = haversine_m(coords[a], coords[b])
                if length <= 0:
                    continue
                graph.adjacency.setdefault(a, []).append(Edge(a, b, length, way["id"]))
                graph.adjacency.setdefault(b, []).append(Edge(b, a, length, way["id"]))
                graph.way_of_edge[(a, b)] = way["id"]
                graph.way_of_edge[(b, a)] = way["id"]
                service = way.get("service") or "mainline"
                graph.service_of_edge[(a, b)] = service
                graph.service_of_edge[(b, a)] = service
        return graph

    @property
    def node_count(self) -> int:
        return len(self.adjacency)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.adjacency.values()) // 2

    def edge_length(self, a: int, b: int) -> float:
        """Geometric length of the edge a->b (0 if absent)."""
        for edge in self.adjacency.get(a, []):
            if edge.b == b:
                return edge.length_m
        return 0.0

    def snap(
        self,
        code: str,
        point: tuple[float, float],
        accept_m: float,
        review_m: float,
        max_edges: int | None = None,
    ) -> SnapResult:
        """Snap a station to the nearest edge, splitting it at the projection.

        A split inserts a synthetic node so a later route from this station
        measures the true remaining length instead of overshooting.
        """
        best: tuple[float, int, int, tuple[float, float]] | None = None
        for edges in self.adjacency.values():
            for edge in edges:
                if edge.a > edge.b:
                    continue  # each undirected edge once
                projected, distance, _t = project_point_to_segment(
                    point, self.coords[edge.a], self.coords[edge.b]
                )
                if best is None or distance < best[0]:
                    best = (distance, edge.a, edge.b, projected)

        if best is None:
            return SnapResult(code, None, None, None, None, None, "rejected")

        distance, a, b, projected = best
        band = "ok" if distance <= accept_m else ("review" if distance <= review_m else "rejected")
        if band == "rejected":
            return SnapResult(code, None, None, None, distance, (a, b), band)

        # Split the edge at the projection: a -> new -> b.
        new_id = self._split_edge(a, b, projected)
        return SnapResult(code, new_id, projected[0], projected[1], distance, (a, b), band)

    def _split_edge(self, a: int, b: int, projected: tuple[float, float]) -> int:
        """Insert a synthetic node between a and b, returning its id.

        The original a-b edge is REPLACED by a-new and new-b, and the synthetic
        node is wired in both directions. Getting this wrong isolates the station
        from the network, which is exactly what an earlier version did.
        """
        new_id = self._next_synthetic()
        self.coords[new_id] = projected
        length_a = haversine_m(self.coords[a], projected)
        length_b = haversine_m(projected, self.coords[b])
        way = self.way_of_edge.get((a, b), 0)
        # Synthetic split edges inherit the original edge's service class, so a
        # station's own stub is not counted as an unknown class.
        service = self.service_of_edge.get((a, b), "mainline")

        # Remove the original edge in both directions.
        self.adjacency[a] = [e for e in self.adjacency.get(a, []) if not (e.a == a and e.b == b)]
        self.adjacency[b] = [e for e in self.adjacency.get(b, []) if not (e.a == b and e.b == a)]

        # Wire a -> new -> b and the reverse.
        self.adjacency[a].append(Edge(a, new_id, length_a, way))
        self.adjacency[b].append(Edge(b, new_id, length_b, way))
        self.adjacency[new_id] = [
            Edge(new_id, a, length_a, way),
            Edge(new_id, b, length_b, way),
        ]

        for key in ((a, new_id), (new_id, a), (b, new_id), (new_id, b)):
            self.way_of_edge[key] = way
            self.service_of_edge[key] = service
        self.way_of_edge.pop((a, b), None)
        self.way_of_edge.pop((b, a), None)
        return new_id

    _synthetic = 0

    def _next_synthetic(self) -> int:
        RailGraph._synthetic -= 1
        return RailGraph._synthetic

    def bridge_gaps(self, max_gap_m: float) -> int:
        """Join dangling endpoints that are closer than ``max_gap_m``.

        OSM frequently digitises two ways that meet at a few metres without
        sharing a node; the network then looks disconnected even though the track
        is continuous. Bridging only (a) endpoints of degree 1 and (b) gaps under
        the configured limit keeps this honest: a real missing line is far larger.

        Returns the number of bridges added. Every bridge is a synthetic edge and
        is reported, so it is never invisible.
        """
        if max_gap_m <= 0:
            return 0

        dangling = [node for node, edges in self.adjacency.items() if len(edges) == 1]
        bridged = 0
        used: set[int] = set()

        # Grid index so this stays O(n) rather than O(n^2) for ~300 endpoints.
        cell = 0.0005  # ~55 m in lat, ~50 m in lon at Java latitudes
        grid: dict[tuple[int, int], list[int]] = {}
        for node in dangling:
            lat, lon = self.coords[node]
            grid.setdefault((int(lat / cell), int(lon / cell)), []).append(node)

        for node in dangling:
            if node in used:
                continue
            lat, lon = self.coords[node]
            gi, gj = int(lat / cell), int(lon / cell)
            best: tuple[float, int] | None = None
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for other in grid.get((gi + di, gj + dj), []):
                        if other == node or other in used:
                            continue
                        gap = haversine_m(self.coords[node], self.coords[other])
                        if gap <= max_gap_m and (best is None or gap < best[0]):
                            best = (gap, other)
            if best is None:
                continue
            gap, other = best
            self.adjacency[node].append(Edge(node, other, gap, 0))
            self.adjacency[other].append(Edge(other, node, gap, 0))
            self.way_of_edge[(node, other)] = 0
            self.way_of_edge[(other, node)] = 0
            # A synthetic topology repair is mainline-equivalent for reporting.
            self.service_of_edge[(node, other)] = "gap_bridge"
            self.service_of_edge[(other, node)] = "gap_bridge"
            used.add(node)
            used.add(other)
            bridged += 1
        return bridged
