.PHONY: setup inventory extract parse validate build-db geometry test lint fmt serve clean

PDF ?= data/input/GAPEKA_2026.pdf

setup: ## install dependencies
	uv sync

inventory: ## classify PDF pages -> data/raw/inventory.json + docs/inventory_report.md
	uv run python -m pipeline.inventory --pdf $(PDF)

extract: ## PDF -> raw
	@echo "not implemented yet (Phase 1)"
	@exit 0

parse: ## raw -> parsed
	@echo "not implemented yet (Phase 1)"
	@exit 0

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
