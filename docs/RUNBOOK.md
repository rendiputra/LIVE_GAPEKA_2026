# RUNBOOK — operating this project

Two halves: the **offline pipeline** (PDF → clean data → static export) and the
**static site** (no server; positions computed in the browser). Nothing here uses
an LLM at runtime.

## 0. Prerequisites

| Tool | Why |
|---|---|
| `uv` | Python 3.12 + dependencies |
| `pnpm` | frontend dependencies |
| PyMuPDF, pdfplumber, `pdftotext` | PDF extraction and cross-checks (`make doctor`) |
| `pmtiles` (or `go-pmtiles`) | basemap extract (`go install github.com/protomaps/go-pmtiles@latest`) |
| `wrangler` | R2 upload (deploy only) |

`make setup` then `make doctor` must both succeed before anything else.

## 1. Processing a NEW or REVISED Gapeka

The order matters: the database writes station coordinates that geometry reads.

```bash
# 1. put the PDF in place (never committed)
cp <new-gapeka>.pdf data/input/GAPEKA_2026.pdf
shasum -a 256 data/input/GAPEKA_2026.pdf      # record this

# 2. inventory + classification
make inventory                                  # docs/inventory_report.md

# 3. extract and parse
make extract
make parse-intercity                            # Book 1, validated, gated
#    Book 2 equivalent follows the same path

# 4. database FIRST (writes station_coordinates.json), then geometry, then DB again
make build-db
make geometry                                   # segments + trip status
make build-db                                   # settles station coordinates

# 5. quality reports (nothing is auto-fixed)
make triple          # rail-path neighbour triples
make snap-audit      # every station's snap distance
make day-offsets     # midnight-straddling rows
make suspects        # suspect-segment review page + draft bridges
make coverage        # why trips are hidden, top blockers
make v15             # endpoint cross-check vs index + summary tables

# 6. verify reproducibility before trusting the numbers
make reproduce       # must print REPRODUCIBLE
```

**If `make reproduce` fails**, stop. The build depends on something that is not
tracked; find it before continuing (see §5).

## 2. Human decisions (never automated)

| File | Decision |
|---|---|
| `data/config/station_overrides.yaml` | a station's coordinate |
| `data/config/station_aliases.yaml` | official names, `conflict_resolutions` |
| `data/config/segment_reviews.yaml` | `accept_route` / `needs_bridge` per suspect segment |
| `data/config/geometry_bridges.yaml` | join two OSM nodes (a digitising seam) |
| `data/config/snap_pins.yaml` | which track a station is on |
| `data/config/rejected_stations.yaml` | coordinates that must not be routed |

All are tracked in git. The pipeline only reads them. A human edits, then re-runs
`make geometry && make build-db && make reproduce`.

Coordinate safety gate: `python -m pipeline.override_gate CODE LAT LON --snap-max-m 50`.

## 3. Human verification (required before release)

```bash
make verify-sheet                               # data/review/verification_sheet.html
#   open it, compare against the PDF images, mark wrong rows, add notes
#   click "Unduh verification_result.json"
make import-verifications FILE=~/Downloads/verification_result.json
#   (or: uv run python -m pipeline.import_verifications <file>)
make test                                       # golden fixtures must pass
make verify-status                              # docs/verification_status.md
```

A trip is promoted to `tests/golden/verified_*.json` **only** when every row
matched. Wrong rows land in `data/review/verification_findings.json` and are never
fixed automatically.

## 4. Releasing the static site

```bash
make export-web                                 # web/public/data/
make parity                                     # engine/parity_frames.json
make web-test                                   # Vitest + parity
make web-e2e                                    # Playwright
make basemap                                    # tiles + glyphs (network)
make web-build                                  # web/dist/ (tiles pruned)
make web-lighthouse                             # data/review/lighthouse.json
make reports                                    # all generated docs
```

Then follow `docs/DEPLOY.md`: upload the site and the tiles to **separate** R2
buckets, apply CORS, verify a Range request returns `206`.

```bash
make deploy-plan                                # dry-run: plan, upload, cors, rollback
R2_SITE_BUCKET=... R2_TILE_BUCKET=... uv run python -m pipeline.deploy_r2 upload --apply
```

### Rollback

Static hosting has nothing to migrate: re-upload the previous release's
`index.html` + `assets/`. Tiles are immutable and dated. Verify the About dialog's
data version hash, then `curl -r 0-99 -o /dev/null -w "%{http_code}" <tile-url>`
must print `206`.

## 5. When something looks wrong

| Symptom | First check |
|---|---|
| `make reproduce` fails | an untracked file is being read; grep for `data/review/` in `pipeline/` |
| a trip is missing from the map | `make coverage`, then `trip_geometry_status` |
| a route is absurdly long | `make suspects`; compare the nearest track vs an adjacent way |
| a station is in the wrong place | `make snap-audit` (distance and band) |
| parity fails | the TS port drifted from `engine/position.py`; fix the port, never the tolerance |
| validation gate fails | fix the data or ask; never loosen the rule |

## 6. What is never committed

The PDF, raw words, parsed data, the database, OSM extracts, external datasets,
tiles, page images and generated web data. `git check-ignore <path>` must print
the path before you commit anything new.
