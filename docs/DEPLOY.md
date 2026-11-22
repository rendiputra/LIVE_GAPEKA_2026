# Deploy — static hosting

The web app is a static bundle. There is no server, no database, and no runtime
API.

## Build

```bash
make export-web      # web/public/data/  (gitignored, generated)
make web-build       # web/dist/         (gitignored, generated)
```

`web/dist/` is the only artefact to publish.

## Hosting

Any static host works (S3 + CloudFront, Cloudflare Pages, Netlify, nginx, GitHub
Pages). Requirements:

1. Serve `index.html` for `/`.
2. Serve `data/*.json` with `Content-Type: application/json` and a long
   `Cache-Control` (they are content-hashed by name; `manifest.json` must be
   `no-cache` so a new deploy is picked up).
3. HTTPS. The Web Worker and `fetch` of the data files need a secure context in
   practice.

## Tile provider — decided: Protomaps PMTiles, self-hosted (ADR 009)

```bash
make basemap     # extracts web/public/tiles/java.pmtiles + self-hosted glyphs/sprites
make web-build
```

`make basemap` pulls a region extract from the Protomaps daily planet build using
`pmtiles extract` (HTTP range requests, so only Java is downloaded) and records
the build date in `web/public/tiles/manifest.json`. It also downloads the glyphs
and sprites the style needs, so the site has **no runtime CDN**.

The tile source is one setting, `web/src/config.ts`:

| `VITE_TILE_MODE` | Source | Allowed |
|---|---|---|
| `pmtiles` (default) | self-hosted `tiles/java.pmtiles` | production |
| `osm` | public `tile.openstreetmap.org` raster | **development only** |

A production `vite build` **fails** if `VITE_TILE_MODE=osm`. That is deliberate:
the OSM Foundation's tile usage policy forbids this traffic, so shipping it is a
policy violation, not a bug.

### Host the tiles separately from the static site

`java.pmtiles` is ~260 MB. Many static hosts cap single-object size and few serve
`Range` requests well, and PMTiles **requires** byte-range support. Host it on
object storage instead:

1. Upload `web/public/tiles/java.pmtiles` (and `tiles/assets/**`) to a bucket
   (S3, R2, GCS, Backblaze B2).
2. Enable `Range` requests — S3 and R2 do this by default; verify with
   `curl -r 0-99 -o /dev/null -w "%{http_code}" <url>` which must print `206`.
3. Set `Access-Control-Allow-Origin: *` (or your site's origin) and
   `Access-Control-Allow-Headers: Range`, plus
   `Access-Control-Expose-Headers: Content-Range, Content-Length, Accept-Ranges`.
4. Cache hard: `Cache-Control: public, max-age=31536000, immutable`. The filename
   should carry the build date (e.g. `java-20261120.pmtiles`) so a new extract
   gets a new URL.
5. Point `PMTILES_URL` in `web/src/config.ts` at the absolute bucket URL.

The glyphs and sprites (`tiles/assets/`, ~1.8 MB) can live on the static site
itself; they are small and fetched normally.

Record the final provider and URL in `docs/LEGAL_CHECKLIST.md`.

## Legal items

Before public release, work through `docs/LEGAL_CHECKLIST.md`. Nothing there is
resolved by this repository.
