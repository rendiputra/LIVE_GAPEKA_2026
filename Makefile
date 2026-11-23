.PHONY: setup doctor inventory extract parse parse-intercity conflicts validity summary-tables stations build-db phase3a verify-status validate geometry geometry-baseline triple engine-sweep engine-replay suspects coverage h5h6 day-offsets bridge-probe snap-experiment verify-sheet import-verifications v15 snap-audit station-spacing basemap web-assets export-web parity web-dev web-build web-test web-e2e web-lighthouse deploy-plan reports test lint fmt serve clean

PDF ?= data/input/GAPEKA_2026.pdf

setup: ## install dependencies
	uv sync

doctor: ## report which required/optional tools are available
	uv run python -m pipeline.doctor

inventory: ## classify PDF pages -> data/raw/inventory.json + docs/inventory_report.md
	uv run python -m pipeline.inventory --pdf $(PDF)

extract: ## PDF -> raw words (append-only)
	uv run python -m pipeline.extract_words --pdf $(PDF)

parse: ## raw -> parsed (index + pilot tables + V1-V3)
	uv run python -m pipeline.parse_pilot --pdf $(PDF)

parse-intercity: ## Phase 2a: parse all of intercity Book 1, validate, gate
	uv run python -m pipeline.parse_intercity --pdf $(PDF)

conflicts: ## station-name conflicts report (evidence only)
	uv run python -m pipeline.station_conflicts

validity: ## extract validity dates from every divider page
	uv run python -m pipeline.validity

summary-tables: ## Lampiran IV REGULER/FAKULTATIF vs F-suffix evidence
	uv run python -m pipeline.summary_report

validate: ## run all validators; fail on any violation
	@echo "not implemented yet (Phase 2) -- failing closed on purpose"
	@exit 1

stations: ## match PDF station codes to external coordinates
	uv run python -m pipeline.match_stations

build-db: ## validated -> SQLite database
	uv run python -m pipeline.build_db

phase3a: ## full MVP assembly: stations + db + cross-checks + report
	uv run python -m pipeline.phase3a_report

verify-status: ## regenerate docs/verification_status.md
	uv run python -m pipeline.verification_status

geometry: ## OSM -> segments + trip geometry status (Phase 4)
	uv run python -m pipeline.build_geometry

geometry-baseline: ## reproduce the pre-Q1/Q4 state into data/review/t1_before.json
	uv run python -m pipeline.build_geometry --baseline

triple: ## rail-path neighbour-consistency triples (Q3)
	uv run python -m pipeline.triple_rail

engine-sweep: ## R1: 24 h sweep + benchmark -> data/review/r1_engine_sweep.json
	uv run python -m pipeline.engine_sweep

engine-replay: ## R2: self-contained Leaflet replay -> data/review/engine_replay.html
	uv run python -m pipeline.engine_replay

suspects: ## suspect-segment review page + draft bridge candidates (T2)
	uv run python -m pipeline.suspect_review

coverage: ## why trips are hidden + top blockers (T3)
	uv run python -m pipeline.coverage_blockers

h5h6: ## rail-path gate record for H5/H6
	uv run python -m pipeline.h5_h6

day-offsets: ## midnight-straddling rows (Q3)
	uv run python -m pipeline.day_offsets

bridge-probe: ## measure each draft bridge candidate (P4), nothing applied
	uv run python -m pipeline.bridge_probe

snap-experiment: ## routing-aware snapping experiment (Q1b), nothing applied
	uv run python -m pipeline.snap_experiment

verify-sheet: ## build the 20-train human verification sheet (T1)
	uv run python -m pipeline.verification_sheet

import-verifications: ## ingest verification_result.json (T1); FILE=... to override
	uv run python -m pipeline.import_verifications $(FILE)

v15: ## V15 endpoint cross-check, all trips (T2)
	uv run python -m pipeline.v15_endpoints

snap-audit: ## every station's snap distance and band (T3)
	uv run python -m pipeline.snap_audit

basemap: ## extract the Java PMTiles basemap + self-host glyphs/sprites (T5)
	uv run python -m pipeline.basemap
	uv run python -m pipeline.web_assets

web-assets: ## only the glyphs and sprites (T5)
	uv run python -m pipeline.web_assets

station-spacing: ## F4 report: run-together station names, nothing renamed
	uv run python -m pipeline.station_spacing

export-web: ## export the static schedule into web/public/data (B1)
	uv run python -m pipeline.export_web

parity: ## export parity frames for the TypeScript port (B3)
	uv run python -m pipeline.parity_frames

web-dev: export-web ## Vite dev server
	cd web && pnpm install --silent && pnpm dev

web-build: export-web ## static production build into web/dist
	cd web && pnpm install --silent && pnpm build

web-test: export-web parity ## Vitest unit + parity
	cd web && pnpm install --silent && pnpm test

web-e2e: export-web ## Playwright smoke + robustness with tiles stubbed
	cd web && pnpm e2e

web-lighthouse: ## Lighthouse mobile report -> data/review/lighthouse.json (T7)
	cd web && pnpm build:e2e && (pnpm exec vite preview --outDir dist-e2e --port 4173 --strictPort --host 127.0.0.1 &) && sleep 4 && node e2e/lighthouse.mjs; pkill -f "vite preview" || true

reproduce: ## prove a clean clone rebuilds identical hashes (P2)
	uv run python -m pipeline.reproduce

deploy-plan: ## R2 deploy plan and dry-runs (Q3/Q5), touches nothing
	uv run python -m pipeline.deploy_r2 plan
	uv run python -m pipeline.deploy_r2 upload --dry-run
	uv run python -m pipeline.deploy_r2 cors --dry-run
	uv run python -m pipeline.deploy_r2 rollback --dry-run

reports: ## regenerate the generated reports
	uv run python -m pipeline.phase4d_report
	uv run python -m pipeline.phase5b_report
	uv run python -m pipeline.phase5c_report
	uv run python -m pipeline.phase5d_report
	uv run python -m pipeline.phase6a_report
	uv run python -m pipeline.phase6b_report
	uv run python -m pipeline.phase6c_report
	uv run python -m pipeline.phase6d_report
	uv run python -m pipeline.phase5_report
	uv run python -m pipeline.verification_status

test: ## unit + golden
	uv run pytest

lint: ## ruff check + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## apply formatting
	uv run ruff check --fix .
	uv run ruff format .

serve: ## API + web dev
	@echo "not implemented yet (Phase 6)"
	@exit 0

clean:
	rm -rf .pytest_cache .ruff_cache
