# ADR 010 — OpenFreeMap basemap with optional OpenRailwayMap overlays

- Status: accepted (frontend revamp, Turn 1)
- Date: 2026-11-23
- Supersedes: ADR 009 **for `frontend/` only**. ADR 009 stays in force for `web/`.
- Context: which basemap the clean-room frontend ships, and how railway data is layered on it

## Context

ADR 009 chose a **self-hosted Protomaps PMTiles extract** of Java for `web/`, with
local glyphs and sprites and a build-time refusal to fall back to the public OSM
tile server. That works, and `web/` keeps it.

The revamp changes the constraint: the frontend must be deployable as a plain
static bundle with no tile pipeline, no ~260 MB artefact to host separately, no
Range/CORS configuration to get right, and no build step that can silently ship a
stale archive. ADR 009's own consequences section is the argument against it here:
one more storage bucket, one more upload, one more thing that goes stale.

## Decision

1. **No self-hosted PMTiles for `frontend/`.** `java.pmtiles`, the `pmtiles`
   package and the extract step are not part of this bundle.
2. **Default basemap: OpenFreeMap vector tiles**, consumed directly as a MapLibre
   style. Two styles, both supported:
   - `positron` — the default: a light, low-contrast basemap that keeps the
     schedule overlay as the figure and the map as the ground;
   - `liberty` — selectable by the user.
3. **Our exported Gapeka rail geometry is always drawn on top**: the 391 routed
   segments from `python -m pipeline.export_web`, as a dedicated layer that does
   not depend on the basemap's own rail rendering. This is the layer that carries
   meaning (a train is here, on this segment); the basemap is context.
4. **Optional overlays, via a Google-Maps-style Layer Switcher, BOTH OFF by
   default:**
   - OpenRailwayMap `Infrastruktur` — `https://www.openrailwaymap.org/standard/`
   - OpenRailwayMap `Max Speed` — `https://www.openrailwaymap.org/maxspeed/`

   They are raster overlays (XYZ tiles), so enabling one adds a raster source to
   the running style; it never changes the basemap style underneath.
5. **Attribution is mandatory and explicit.** The About modal names
   OpenStreetMap/ODbL, OpenFreeMap and OpenRailwayMap. Enabling an overlay does not
   change what is attributed; the attribution is always complete.

## Why

- **Zero hosting for the basemap.** OpenFreeMap serves the tiles; the bundle is
  HTML, JS and our own JSON. The release gate no longer needs a separate bucket, a
  Range check or a CORS rule for tiles.
- **Vector tiles at the right weight.** `positron` is deliberately quiet, which is
  what a data overlay needs. `liberty` is available for users who want more
  geographic detail, without maintaining two tile sets ourselves.
- **The railway layer is ours, not the basemap's.** Drawing the 391 exported
  segments means the visible track matches the geometry the engine estimates on.
  Trusting a basemap's own railway styling would show tracks we do not route on,
  and hide segments the basemap generalises away.
- **Overlays default to OFF** because they answer a different question ("what
  infrastructure exists here?") from the app's ("where is this train now?"). On by
  default they would compete with the schedule layer and slow first paint.
- **OpenRailwayMap is the reference for Indonesian rail infrastructure** that we do
  not have in our own export (signalling, line speed), so it is the right overlay
  to offer rather than re-deriving it.

## Consequences

- Runtime depends on OpenFreeMap availability. This is accepted: the app already
  requires a network for the schedule payload, and a failed basemap leaves the
  schedule layers and the UI usable (the map degrades to a blank ground, not a
  broken app). The engine is offline-capable by construction — it never fetches.
- **A public-tile policy question moves rather than disappears.** ADR 009's
  build-time refusal to use the public OSM tile server must be restated for
  OpenFreeMap/OpenRailwayMap usage terms before public launch; this belongs on
  `docs/LEGAL_CHECKLIST.md`, and the tile-provider gate in AGENTS.md §7 (item 3)
  is rewritten to "OpenFreeMap in use, usage terms recorded, no public OSM tile
  server" instead of "PMTiles manifest exists".
- Style switching (`positron` ↔ `liberty`) must preserve the Gapeka layer, the
  selected overlay and the camera. Rebuilding the style from scratch on switch
  would drop them; the implementation re-adds sources and layers explicitly and is
  covered by a test.
- No glyph or sprite self-hosting step. The style's own fonts come from
  OpenFreeMap; self-hosted **UI** fonts (`@fontsource/*`) remain local, so the
  application's typography never depends on a CDN.

## Alternatives considered

- **Keep PMTiles (ADR 009).** Rejected for `frontend/`: it optimises for
  independence from third-party availability at the cost of an operational
  pipeline the revamp is trying to remove. Still correct for `web/`.
- **Public OSM raster tiles.** Rejected: explicitly disallowed for this traffic,
  and visually the heaviest option under a data overlay.
- **MapTiler / commercial vector tiles.** Viable, but ships an API key in the
  client and adds a per-request cost for a basemap that changes rarely.
- **Blank canvas, no basemap.** Rejected: without coastlines and place names the
  map is unreadable to anyone who does not already know Java's geography.
- **OpenRailwayMap overlays ON by default.** Rejected: it answers a different
  question, competes with the schedule layer, and doubles tile requests on first
  load.
