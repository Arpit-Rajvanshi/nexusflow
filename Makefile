# NexusFlow Makefile
# Automates common development tasks.
# Run `make help` to see all available commands.

.PHONY: help up down infra-up logs build lint typecheck test test-cov \
        migrate migrate-create db-shell redis-shell clean fmt \
        gateway orchestrator planner worker-all scale-retrievers

SHELL := /bin/bash
COMPOSE := docker compose
PYTHON := python

# Default: show help
.DEFAULT_GOAL := help

## ─── Infrastructure ────────────────────────────────────────────────────────

up: ## Start all services in detached mode
	@echo "🚀 Starting NexusFlow..."
	$(COMPOSE) up -d
	@echo "✅ All services started. Dashboard: http://localhost:3000"

down: ## Stop all services (keeps volumes)
	$(COMPOSE) down

down-v: ## Stop all services and remove volumes (destructive!)
	$(COMPOSE) down -v

infra-up: ## Start only postgres + redis
	$(COMPOSE) up -d postgres redis
	@echo "✅ Infra up. Postgres: 5432, Redis: 6379"

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

logs-%: ## Tail logs for a specific service (e.g. make logs-gateway)
	$(COMPOSE) logs -f $*

build: ## Rebuild all Docker images
	$(COMPOSE) build --no-cache

restart-%: ## Restart a specific service (e.g. make restart-orchestrator)
	$(COMPOSE) restart $*

## ─── Development ───────────────────────────────────────────────────────────

dev-setup: ## First-time local setup (copy .env, install deps)
	@cp -n .env.example .env || true
	@echo "📝 .env created from .env.example — fill in your OPENAI_API_KEY"
	pip install -r requirements.txt -r requirements-dev.txt
	pip install -e .
	pre-commit install
	@echo "✅ Dev environment ready"

gateway: ## Run gateway locally (no Docker)
	uvicorn nexusflow.services.gateway.app:app --host 0.0.0.0 --port 8000 --reload

streaming: ## Run streaming gateway locally
	uvicorn nexusflow.services.streaming.app:app --host 0.0.0.0 --port 8001 --reload

orchestrator: ## Run orchestrator locally
	$(PYTHON) -m nexusflow.services.orchestrator.main

planner: ## Run planner service locally
	$(PYTHON) -m nexusflow.services.planner.main

worker-all: ## Run all 5 agent workers locally (background processes)
	@echo "Starting all agent workers..."
	AGENT_TYPE=retriever $(PYTHON) -m nexusflow.agents.runner &
	AGENT_TYPE=analyzer $(PYTHON) -m nexusflow.agents.runner &
	AGENT_TYPE=writer $(PYTHON) -m nexusflow.agents.runner &
	AGENT_TYPE=validator $(PYTHON) -m nexusflow.agents.runner &
	AGENT_TYPE=planner $(PYTHON) -m nexusflow.agents.runner &
	@echo "✅ All workers started. Use 'kill %1 %2 %3 %4 %5' to stop."

scale-retrievers: ## Scale retriever workers to 3 instances
	$(COMPOSE) up -d --scale worker-retriever=3

## ─── Database ──────────────────────────────────────────────────────────────

migrate: ## Apply all pending Alembic migrations
	alembic upgrade head

migrate-down: ## Roll back last migration
	alembic downgrade -1

migrate-create: ## Create a new migration (usage: make migrate-create MSG="add_index")
	alembic revision --autogenerate -m "$(MSG)"

db-shell: ## Open psql shell to nexusflow database
	$(COMPOSE) exec postgres psql -U nexusflow -d nexusflow

redis-shell: ## Open redis-cli
	$(COMPOSE) exec redis redis-cli

redis-monitor: ## Monitor all Redis commands in real-time (dev only!)
	$(COMPOSE) exec redis redis-cli monitor

## ─── Code Quality ──────────────────────────────────────────────────────────

lint: ## Run ruff linter
	ruff check nexusflow/ tests/

fmt: ## Format code with black + ruff
	black nexusflow/ tests/
	ruff check --fix nexusflow/ tests/

typecheck: ## Run mypy type checker
	mypy nexusflow/ --ignore-missing-imports

## ─── Testing ───────────────────────────────────────────────────────────────

test: ## Run all tests
	pytest tests/ -v

test-unit: ## Run only unit tests
	pytest tests/unit/ -v

test-integration: ## Run integration tests (requires running infra)
	pytest tests/integration/ -v --timeout=60

test-cov: ## Run tests with coverage report
	pytest tests/ --cov=nexusflow --cov-report=html --cov-report=term
	@echo "📊 HTML report: htmlcov/index.html"

## ─── Benchmarks ─────────────────────────────────────────────────────────

bench-gateway: ## Run locust load test against gateway
	locust -f benchmarks/locustfile.py --host=http://localhost:8000

## ─── Utilities ─────────────────────────────────────────────────────────────

clean: ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov

submit-task: ## Submit a demo task via curl (requires running gateway)
	@TOKEN=$$(curl -s -X POST http://localhost:8000/auth/token \
		-H "Content-Type: application/json" \
		-d '{"username":"demo","password":"demo"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])"); \
	curl -s -X POST http://localhost:8000/api/v1/tasks \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"title":"AI Chip Startup Analysis","description":"Research leading AI chip startups, compare their latest funding rounds, analyze market trends, and generate a comprehensive investor report.","priority":5}' \
		| python -m json.tool

## ─── Help ───────────────────────────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_%-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' | \
		sort
	@echo ""
	@echo "Usage: make [target]"
