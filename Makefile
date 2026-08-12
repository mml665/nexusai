.PHONY: help up down build rebuild logs test lint clean init

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start all services (docker compose up)
	docker compose up -d

down: ## Stop all services
	docker compose down

build: ## Build all services
	docker compose build

rebuild: ## Rebuild all services (no cache) and restart
	docker compose down
	docker compose build --no-cache
	docker compose up -d

logs: ## Tail logs for all services
	docker compose logs -f --tail=100

logs-%: ## Tail logs for a specific service (e.g., make logs-gateway)
	docker compose logs -f --tail=100 $*

init: ## Initialize database (destroy existing data)
	docker compose down -v
	docker compose up -d postgres redis elasticsearch
	@echo "Waiting for PostgreSQL..."
	@sleep 10
	docker compose up -d

test: ## Run unit tests
	pip install -r requirements-dev.txt
	pytest tests/ -m unit -v --tb=short

test-all: ## Run all tests (including integration)
	pytest tests/ -v --tb=short

lint: ## Run linter
	ruff check services/ tests/

lint-fix: ## Fix linting issues
	ruff check --fix services/ tests/

format: ## Format code
	ruff format services/ tests/

clean: ## Clean up containers, volumes, and images
	docker compose down -v
	docker system prune -f

ps: ## Show running containers
	docker compose ps

shell-%: ## Shell into a service container (e.g., make shell-gateway)
	docker compose exec $* bash || docker compose exec $* sh
