.PHONY: setup doctor inventory extract parse parse-intercity conflicts validity summary-tables stations build-db phase3a verify-status validate geometry geometry-baseline triple engine-sweep engine-replay reports test lint fmt serve clean

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

reports: ## regenerate the generated reports
	uv run python -m pipeline.phase4d_report
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
