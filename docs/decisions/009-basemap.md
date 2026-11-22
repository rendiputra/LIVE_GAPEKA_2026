# ADR 009 — Self-hosted Protomaps PMTiles basemap

- Status: accepted (Phase 6b)
- Date: 2026-11-22
- Context: which basemap to ship, and how to host it

## Decision

The basemap is a **self-hosted Protomaps PMTiles extract** of Java, produced by
`make basemap`:

- source: the Protomaps daily planet build, `https://build.protomaps.com/YYYYMMDD.pmtiles`
- extraction: `pmtiles extract` with `--bbox=105.0,-8.9,114.7,-5.8 --maxzoom=14`,
  which uses HTTP range requests and downloads only the region
- output: `web/public/tiles/java.pmtiles` (gitignored), plus a manifest with the
  build date and the OSM data timestamp
- style: the bundled `@protomaps/basemaps` light theme with `lang: "id"`
- glyphs and sprites: downloaded by `python -m pipeline.web_assets` into
  `web/public/tiles/assets/`, so there is **no runtime CDN**

The tile source is one setting, `VITE_TILE_MODE` (`pmtiles` default, `osm` for
development only). A production build **fails** if it would use the public OSM
tile server.

## Why

- **No API key.** Nothing secret ships in the client.
- **No per-request cost** and no third-party availability dependency: the archive
  is a file on storage we control.
- **Self-contained**: glyphs and sprites are local, so the page makes no request
  to a CDN it does not own.
- **Indonesian labels** come from the theme's `name:id` support, so the map matches
  the rest of the UI.
- The public OSM tile server explicitly forbids this traffic, so it cannot be the
  production source; a rule that only lives in a comment will eventually be
  broken, hence the build-time failure.

## Consequences

- `java.pmtiles` is ~260 MB and must be hosted separately from the static site,
  on object storage with `Range` support and CORS (`docs/DEPLOY.md`).
- A basemap refresh means re-running `make basemap` and re-uploading; the filename
  should carry the build date so caches cannot go stale.
- The archive's OSM snapshot date is recorded, so the map's age is knowable.
- Lighthouse is measured with tiles stubbed; the score describes the app, not the
  provider.

## Alternatives considered

- **Public OSM raster tiles.** Rejected: disallowed for this traffic.
- **MapTiler or another commercial provider.** Viable, but adds a key and a
  per-request cost for a map that changes rarely.
- **Raster tiles generated locally.** Rejected: much larger for the same area and
  no label localisation.
