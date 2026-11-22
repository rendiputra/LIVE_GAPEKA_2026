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

## Tile provider — decision required before launch

The development build uses **public OpenStreetMap raster tiles**:

```
https://tile.openstreetmap.org/{z}/{x}/{y}.png
```

**These must not be used for production traffic.** The OSM Foundation's tile usage
policy forbids heavy or bulk use, and a public map app qualifies. Before launch,
choose one of:

| Option | Notes |
|---|---|
| **Protomaps / PMTiles** | A single `.pmtiles` file on your own storage. No per-request cost, full control. Best fit for a static site. |
| **MapTiler** | Commercial, has a free tier, requires a key in the client (acceptable, it is a tile key not a secret). |
| **Self-hosted tiles** | Highest effort; needed if you must avoid third-party requests entirely. |

The tile URL is a single constant in `web/src/main.ts` (`OSM_TILES`) so the switch
is one line. Record the choice in `docs/LEGAL_CHECKLIST.md`.

## Legal items

Before public release, work through `docs/LEGAL_CHECKLIST.md`. Nothing there is
resolved by this repository.
