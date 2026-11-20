.PHONY: setup doctor inventory extract parse parse-intercity conflicts validity summary-tables validate build-db geometry test lint fmt serve clean

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

build-db: ## validated -> database
	@echo "not implemented yet (Phase 3)"
	@exit 0

geometry: ## OSM -> segments
	@echo "not implemented yet (Phase 4)"
	@exit 0

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
