# Developer commands. Run `make help` for a list.
.DEFAULT_GOAL := help
API := apps/api
WEB := apps/web

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd $(API) && uv sync
	cd $(WEB) && npm ci

up: ## Build and start the full stack with Docker Compose
	docker compose up -d --build --wait

down: ## Stop the stack (keeps the database volume)
	docker compose down

seed: ## Create demo tenants in the running stack (prompts for a password)
	docker compose run --rm api python -m aigentix.cli seed-dev

logs: ## Follow service logs
	docker compose logs -f

migrate: ## Apply migrations against DATABASE_URL (local, outside Docker)
	cd $(API) && uv run alembic upgrade head

api-dev: ## Run the API with auto-reload (local, outside Docker)
	cd $(API) && uv run uvicorn aigentix.main:app --reload --port 8000

worker-dev: ## Run the worker (local, outside Docker)
	cd $(API) && uv run python -m aigentix.worker

web-dev: ## Run the Next.js dev server
	cd $(WEB) && npm run dev

contracts: ## Regenerate OpenAPI document and TypeScript API types
	cd $(API) && uv run python -m aigentix.export_openapi ../../packages/shared-contracts/openapi.json
	cd $(WEB) && npm run gen:api

lint: ## Lint and format-check everything
	cd $(API) && uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
	cd $(WEB) && npm run lint -- --max-warnings 0

typecheck: ## Static type checks (mypy strict + tsc)
	cd $(API) && uv run mypy
	cd $(WEB) && npm run typecheck

test: ## Backend tests (needs PostgreSQL, see README) and frontend unit tests
	cd $(API) && uv run pytest
	cd $(WEB) && npm test

build: ## Production frontend build
	cd $(WEB) && npm run build

e2e: ## Playwright E2E against the running stack (needs E2E_PASSWORD)
	cd $(WEB) && npx playwright test

verify: lint typecheck test build ## Everything CI runs except E2E

.PHONY: help install up down seed logs migrate api-dev worker-dev web-dev contracts lint typecheck test build e2e verify
