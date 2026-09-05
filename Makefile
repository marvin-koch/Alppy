# Convenience targets. `docker compose up` remains the one command that matters.
.PHONY: help up down logs seed test test-api lint typecheck fmt migration layout

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up:            ## Bring up the whole stack with demo data
	docker compose up --build

down:          ## Stop everything and drop the volumes
	docker compose down -v

logs:          ## Follow the api and worker logs
	docker compose logs -f api worker

seed:          ## Re-run the idempotent demo seed
	docker compose exec api python -m alppy.cli seed

test:          ## Every test in the repo
	PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q
	pnpm turbo run test

test-api:      ## Python tests only
	PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q

lint:          ## Lint everything, including the no-colour-literal rule
	.venv/bin/ruff check apps/api
	pnpm lint:css
	node packages/ui/scripts/check-tokens.mjs
	node scripts/check-i18n.mjs
	pnpm turbo run lint

typecheck:     ## mypy + tsc
	.venv/bin/mypy apps/api/alppy
	pnpm turbo run typecheck

fmt:           ## Format
	.venv/bin/ruff format apps/api
	pnpm format

migration:     ## Create a migration: make migration m="add x"
	cd apps/api && ../../.venv/bin/alembic revision --autogenerate -m "$(m)"

layout:        ## Re-export the print geometry to TypeScript
	PYTHONPATH=apps/api .venv/bin/python scripts/export-layout.py
