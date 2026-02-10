# ==============================================================================
# RAG Ollama - Makefile
# ==============================================================================

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Project settings
PYTHON := python3
POETRY := poetry
MANAGE := $(POETRY) run python manage.py
DOCKER_COMPOSE := docker compose
DOCKER_COMPOSE_CPU := $(DOCKER_COMPOSE) -f docker-compose.cpu.yml
DOCKER_COMPOSE_EXT := $(DOCKER_COMPOSE) -f docker-compose.external.yml

# ==============================================================================
# Help
# ==============================================================================

.PHONY: help
help: ## Show this help message
	@printf "\n"
	@printf "  \033[0;36mRAG Ollama\033[0m - Local AI Assistant\n"
	@printf "\n"
	@printf "  \033[0;33mUsage:\033[0m make <target>\n"
	@printf "\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[0;32m%-24s\033[0m %s\n", $$1, $$2}'
	@printf "\n"

# ==============================================================================
# Setup & Install
# ==============================================================================

.PHONY: install
install: ## Install all dependencies via Poetry
	$(POETRY) install

.PHONY: install-prod
install-prod: ## Install production dependencies only
	$(POETRY) install --only main

.PHONY: setup
setup: install env migrate static superuser ## Full local setup (install + env + migrate + static + superuser)
	@printf "\033[0;32mSetup complete!\033[0m\n"
	@printf "Run: make run\n"

.PHONY: env
env: ## Create .env from .env.example (if not exists)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		printf "\033[0;32m.env created from .env.example\033[0m\n"; \
		printf "\033[0;33mEdit .env and set OLLAMA_URL for your setup\033[0m\n"; \
	else \
		printf "\033[0;33m.env already exists, skipping\033[0m\n"; \
	fi

# ==============================================================================
# Django commands
# ==============================================================================

.PHONY: run
run: ## Run Django dev server on 0.0.0.0:8000
	$(MANAGE) runserver 0.0.0.0:8000

.PHONY: migrate
migrate: ## Run Django migrations
	$(MANAGE) migrate --noinput

.PHONY: migrations
migrations: ## Create new migrations
	$(MANAGE) makemigrations

.PHONY: static
static: ## Collect static files
	$(MANAGE) collectstatic --noinput

.PHONY: superuser
superuser: ## Create Django superuser (interactive)
	$(MANAGE) createsuperuser

.PHONY: shell
shell: ## Open Django shell (IPython)
	$(MANAGE) shell

.PHONY: dbshell
dbshell: ## Open database shell
	$(MANAGE) dbshell

.PHONY: flush
flush: ## Flush database (delete all data)
	$(MANAGE) flush --noinput

# ==============================================================================
# Ollama (direct)
# ==============================================================================

.PHONY: ollama-serve
ollama-serve: ## Start Ollama server locally
	ollama serve

.PHONY: ollama-pull
ollama-pull: ## Pull required Ollama models (mistral + nomic-embed-text)
	ollama pull mistral
	ollama pull nomic-embed-text

.PHONY: ollama-status
ollama-status: ## Check Ollama status and available models
	@OLLAMA=$$(grep '^OLLAMA_URL=' .env 2>/dev/null | cut -d= -f2- || echo "http://localhost:11434"); \
	printf "Checking %s ...\n" "$$OLLAMA"; \
	curl -s $$OLLAMA/api/tags | python3 -m json.tool 2>/dev/null || \
		printf "\033[0;31mOllama is not reachable at %s\033[0m\n" "$$OLLAMA"

.PHONY: ollama-check-remote
ollama-check-remote: ## Check remote Ollama connectivity (reads OLLAMA_URL from .env)
	@OLLAMA=$$(grep '^OLLAMA_URL=' .env 2>/dev/null | cut -d= -f2-); \
	if [ -z "$$OLLAMA" ]; then printf "\033[0;31mOLLAMA_URL not set in .env\033[0m\n"; exit 1; fi; \
	printf "Checking remote Ollama at %s ...\n" "$$OLLAMA"; \
	curl -sf --connect-timeout 5 $$OLLAMA/api/tags | python3 -m json.tool 2>/dev/null && \
		printf "\033[0;32mRemote Ollama is reachable\033[0m\n" || \
		printf "\033[0;31mCannot reach Ollama at %s. Check network/firewall.\033[0m\n" "$$OLLAMA"

# ==============================================================================
# Open WebUI
# ==============================================================================

.PHONY: owui-status
owui-status: ## Check Open WebUI connectivity and auth (reads from .env)
	@URL=$$(grep '^OPENWEBUI_URL=' .env 2>/dev/null | cut -d= -f2-); \
	KEY=$$(grep '^OPENWEBUI_API_KEY=' .env 2>/dev/null | cut -d= -f2-); \
	if [ -z "$$URL" ]; then printf "\033[0;31mOPENWEBUI_URL not set in .env\033[0m\n"; exit 1; fi; \
	printf "Checking Open WebUI at %s ...\n" "$$URL"; \
	if [ -n "$$KEY" ]; then \
		curl -sf --connect-timeout 5 -H "Authorization: Bearer $$KEY" $$URL/api/models | python3 -m json.tool 2>/dev/null && \
			printf "\033[0;32mOpen WebUI is reachable, auth OK\033[0m\n" || \
			printf "\033[0;31mCannot reach Open WebUI or auth failed at %s\033[0m\n" "$$URL"; \
	else \
		printf "\033[0;33mOPENWEBUI_API_KEY is empty -- trying without auth...\033[0m\n"; \
		curl -sf --connect-timeout 5 $$URL/api/models | python3 -m json.tool 2>/dev/null && \
			printf "\033[0;32mOpen WebUI is reachable (no auth)\033[0m\n" || \
			printf "\033[0;31mCannot reach Open WebUI at %s\033[0m\n" "$$URL"; \
	fi

.PHONY: owui-models
owui-models: ## List models available in Open WebUI
	@URL=$$(grep '^OPENWEBUI_URL=' .env 2>/dev/null | cut -d= -f2-); \
	KEY=$$(grep '^OPENWEBUI_API_KEY=' .env 2>/dev/null | cut -d= -f2-); \
	if [ -z "$$URL" ]; then printf "\033[0;31mOPENWEBUI_URL not set in .env\033[0m\n"; exit 1; fi; \
	printf "Models at %s:\n" "$$URL"; \
	curl -sf --connect-timeout 5 -H "Authorization: Bearer $$KEY" $$URL/api/models | \
		python3 -c "import sys,json; data=json.load(sys.stdin); [print(f'  - {m.get(\"id\",m.get(\"name\",\"?\"))}') for m in data.get('data',data.get('models',[]))]" 2>/dev/null || \
		printf "\033[0;31mFailed to list models\033[0m\n"

.PHONY: owui-check-key
owui-check-key: ## Validate Open WebUI API key
	@URL=$$(grep '^OPENWEBUI_URL=' .env 2>/dev/null | cut -d= -f2-); \
	KEY=$$(grep '^OPENWEBUI_API_KEY=' .env 2>/dev/null | cut -d= -f2-); \
	if [ -z "$$KEY" ]; then printf "\033[0;31mOPENWEBUI_API_KEY is empty in .env\033[0m\n"; exit 1; fi; \
	printf "Validating API key at %s ...\n" "$$URL"; \
	HTTP_CODE=$$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 \
		-H "Authorization: Bearer $$KEY" $$URL/api/models); \
	if [ "$$HTTP_CODE" = "200" ]; then \
		printf "\033[0;32mAPI key is valid (HTTP 200)\033[0m\n"; \
	elif [ "$$HTTP_CODE" = "401" ] || [ "$$HTTP_CODE" = "403" ]; then \
		printf "\033[0;31mAPI key is INVALID (HTTP %s) -- check OPENWEBUI_API_KEY\033[0m\n" "$$HTTP_CODE"; \
	else \
		printf "\033[0;31mUnexpected response (HTTP %s)\033[0m\n" "$$HTTP_CODE"; \
	fi

# ==============================================================================
# Docker
# ==============================================================================

.PHONY: up
up: ## Start all services with Docker (GPU)
	$(DOCKER_COMPOSE) up -d

.PHONY: up-cpu
up-cpu: ## Start all services with Docker (CPU only)
	$(DOCKER_COMPOSE_CPU) up -d

.PHONY: up-build
up-build: ## Build and start all services (GPU)
	$(DOCKER_COMPOSE) up -d --build

.PHONY: up-build-cpu
up-build-cpu: ## Build and start all services (CPU)
	$(DOCKER_COMPOSE_CPU) up -d --build

.PHONY: up-external
up-external: ## Start Django only, Ollama on remote server (set OLLAMA_URL in .env)
	@OLLAMA=$$(grep '^OLLAMA_URL=' .env 2>/dev/null | cut -d= -f2-); \
	BACKEND=$$(grep '^LLM_BACKEND=' .env 2>/dev/null | cut -d= -f2-); \
	if [ "$$BACKEND" = "openwebui" ]; then \
		OWUI=$$(grep '^OPENWEBUI_URL=' .env 2>/dev/null | cut -d= -f2-); \
		printf "\033[0;36mUsing Open WebUI backend: %s\033[0m\n" "$$OWUI"; \
	elif [ -z "$$OLLAMA" ] || echo "$$OLLAMA" | grep -q 'ollama:11434'; then \
		printf "\033[0;31mSet OLLAMA_URL in .env to the remote server address first!\033[0m\n"; \
		printf "\033[0;33mExample: OLLAMA_URL=http://192.168.1.100:11434\033[0m\n"; \
		exit 1; \
	else \
		printf "\033[0;36mUsing remote Ollama: %s\033[0m\n" "$$OLLAMA"; \
	fi
	$(DOCKER_COMPOSE_EXT) up -d

.PHONY: up-build-external
up-build-external: ## Build and start Django only, Ollama on remote server
	$(DOCKER_COMPOSE_EXT) up -d --build

.PHONY: down
down: ## Stop all Docker services
	$(DOCKER_COMPOSE) down

.PHONY: down-cpu
down-cpu: ## Stop all Docker services (CPU compose)
	$(DOCKER_COMPOSE_CPU) down

.PHONY: down-external
down-external: ## Stop Django (external Ollama compose)
	$(DOCKER_COMPOSE_EXT) down

.PHONY: down-volumes
down-volumes: ## Stop and remove all Docker volumes (WARNING: deletes data)
	$(DOCKER_COMPOSE) down -v

.PHONY: logs
logs: ## Show Docker logs (all services)
	$(DOCKER_COMPOSE) logs -f

.PHONY: logs-ext
logs-ext: ## Show Docker logs (external Ollama compose)
	$(DOCKER_COMPOSE_EXT) logs -f

.PHONY: logs-django
logs-django: ## Show Django container logs
	@if docker ps --format '{{.Names}}' | grep -q rag-django; then \
		docker logs -f rag-django; \
	else \
		printf "\033[0;31mrag-django is not running\033[0m\n"; \
	fi

.PHONY: logs-ollama
logs-ollama: ## Show Ollama container logs
	$(DOCKER_COMPOSE) logs -f ollama

.PHONY: ps
ps: ## Show running Docker containers
	$(DOCKER_COMPOSE) ps

.PHONY: restart
restart: ## Restart all Docker services
	$(DOCKER_COMPOSE) restart

.PHONY: rebuild
rebuild: down up-build ## Rebuild and restart all services

.PHONY: docker-shell
docker-shell: ## Open shell in Django container
	docker exec -it rag-django /bin/bash

.PHONY: docker-superuser
docker-superuser: ## Create Django superuser inside Docker container (interactive)
	docker exec -it rag-django python manage.py createsuperuser

.PHONY: docker-manage
docker-manage: ## Run Django manage.py in container (usage: make docker-manage CMD="migrate")
	docker exec -it rag-django python manage.py $(CMD)

# ==============================================================================
# Linting & Formatting
# ==============================================================================

.PHONY: lint
lint: ## Run ruff lint
	poetry run ruff check . --config pyproject.toml
	@printf "\033[0;32mLint passed\033[0m\n"

.PHONY: lint-fix
lint-fix: ## Run ruff lint with auto-fix
	poetry run ruff check . --fix --config pyproject.toml
	@printf "\033[0;32mLint fix done\033[0m\n"

.PHONY: fmt
fmt: ## Format code with ruff
	poetry run ruff format . --config pyproject.toml
	@printf "\033[0;32mFormatted\033[0m\n"

.PHONY: fmt-check
fmt-check: ## Check formatting without changes
	poetry run ruff format --check . --config pyproject.toml
	@printf "\033[0;32mFormat check passed\033[0m\n"

.PHONY: check
check: lint fmt-check ## Run all checks (lint + format)
	@printf "\033[0;32mAll checks passed\033[0m\n"

# ==============================================================================
# Pre-commit
# ==============================================================================

.PHONY: pre-commit-install
pre-commit-install: ## Install pre-commit hooks
	poetry run pre-commit install --config ../.pre-commit-config.yaml
	@printf "\033[0;32mPre-commit hooks installed\033[0m\n"

.PHONY: pre-commit-run
pre-commit-run: ## Run pre-commit on all files
	poetry run pre-commit run --all-files --config ../.pre-commit-config.yaml
	@printf "\033[0;32mPre-commit passed\033[0m\n"

.PHONY: pre-commit-update
pre-commit-update: ## Update pre-commit hooks to latest versions
	cd .. && poetry run pre-commit autoupdate
	@printf "\033[0;32mPre-commit hooks updated\033[0m\n"

# ==============================================================================
# Testing
# ==============================================================================

.PHONY: test
test: ## Run tests
	poetry run pytest

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	poetry run pytest --cov=core --cov-report=term-missing --cov-report=html
	@printf "\033[0;32mCoverage report: htmlcov/index.html\033[0m\n"

# ==============================================================================
# Cleanup
# ==============================================================================

.PHONY: clean
clean: ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@printf "\033[0;32mCleaned\033[0m\n"

.PHONY: clean-data
clean-data: ## Remove local data (db, chroma, logs)
	rm -f db.sqlite3
	rm -rf chroma_data/
	rm -rf logs/*.log
	rm -rf media/documents/*
	@printf "\033[0;32mData cleaned\033[0m\n"

.PHONY: clean-all
clean-all: clean clean-data ## Remove everything (cache + data)
	rm -rf staticfiles/
	@printf "\033[0;32mAll cleaned\033[0m\n"

# ==============================================================================
# Utility
# ==============================================================================

.PHONY: stats
stats: ## Show project stats via API
	@curl -s http://localhost:8000/api/stats/?api_key=$$(grep API_KEY .env | cut -d= -f2) | \
		python3 -m json.tool 2>/dev/null || printf "\033[0;31mServer is not running\033[0m\n"

.PHONY: tree
tree: ## Show project file structure
	@tree -I '__pycache__|.venv|staticfiles|chroma_data|*.pyc|.git' --dirsfirst 2>/dev/null || \
		find . -not -path './.venv/*' -not -path './.git/*' -not -path './__pycache__/*' \
		-not -name '*.pyc' | sort
