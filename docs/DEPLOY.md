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

### R2 deploy scripts (dry-run by default)

```bash
python -m pipeline.deploy_r2 plan            # sizes + the full plan
python -m pipeline.deploy_r2 upload --dry-run
python -m pipeline.deploy_r2 cors --dry-run
python -m pipeline.deploy_r2 rollback --dry-run
```

`--apply` performs the upload. It **refuses** unless `R2_SITE_BUCKET` and
`R2_TILE_BUCKET` are set, so a dry run can never touch a live bucket by accident.

The build prunes `dist/tiles` after `vite build`: tiles must come from the tile
bucket, never from the site origin. Site bundle after pruning: **11 files,
3.2 MB**. Tiles: **31 files, 262.8 MB** (the PMTiles archive is 261.0 MB).

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
5. Point `PMTILES_URL` in `web/src/config.ts` at the absolute bucket URL, e.g.
   `pmtiles://https://tiles.example.com/java-20261120.pmtiles`, then rebuild.

Use the dated filename. Because the object is immutable and cached for a year, a
new extract must have a new URL or clients keep the old archive.

### Rollback

Static hosting has no migration to undo:

1. keep each build under `releases/<git-sha>/`;
2. to roll back, re-upload the previous release's `index.html` and `assets/`;
3. tiles are immutable and dated, so they only need action if the extract itself
   was wrong — then repoint `PMTILES_URL` and rebuild;
4. verify the About dialog shows the expected data version hash;
5. verify tiles: `curl -r 0-99 -o /dev/null -w "%{http_code}" <url>` prints `206`.

`python -m pipeline.deploy_r2 rollback --dry-run` prints exactly these steps.

The glyphs and sprites (`tiles/assets/`, ~1.8 MB) can live on the static site
itself; they are small and fetched normally.

Record the final provider and URL in `docs/LEGAL_CHECKLIST.md`.

## Legal items

Before public release, work through `docs/LEGAL_CHECKLIST.md`. Nothing there is
resolved by this repository.
