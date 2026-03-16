# =============================================================================
# Boost Data Collector – Developer Makefile
# Wraps docker compose + common Django management commands.
#
# Usage:  make <target>
#         make help     → list all targets
# =============================================================================

SHELL := /bin/bash
COMPOSE   := docker compose
APP       := web
MANAGE    := $(COMPOSE) run --rm $(APP) python manage.py

.DEFAULT_GOAL := help

# ── Help ─────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "  Stack"
	@echo "    build          Build (or rebuild) all images"
	@echo "    up             Clean macOS files, then start all services (detached)"
	@echo "    down           Stop and remove containers (volumes kept)"
	@echo "    stop           Pause all containers (fast restart)"
	@echo "    start          Resume paused containers"
	@echo "    restart        Stop then start all containers"
	@echo "    reset          !! Remove containers AND volumes (wipes DB + data)"
	@echo ""
	@echo "  Logs & status"
	@echo "    ps             Show running containers"
	@echo "    logs           Follow logs for all services"
	@echo "    logs-web       Follow logs for the web service"
	@echo "    logs-worker    Follow logs for the Celery worker"
	@echo "    logs-beat      Follow logs for the Celery beat"
	@echo ""
	@echo "  Django"
	@echo "    migrate        Apply database migrations"
	@echo "    makemigrations Create new migration files"
	@echo "    superuser      Create a Django superuser"
	@echo "    shell          Open Django shell inside the web container"
	@echo "    bash           Open a bash shell inside the web container"
	@echo "    collectstatic  Collect static files"
	@echo ""
	@echo "  Testing (runs locally, not inside Docker)"
	@echo "    test           Run full pytest suite"
	@echo "    test-fast      Run tests, stop on first failure"
	@echo "    test-cov       Run tests with coverage report"
	@echo ""
	@echo "  Utilities"
	@echo "    clean-mac      Remove macOS ._* resource-fork files"
	@echo "    clean-pyc      Remove compiled Python files"
	@echo "    clean          Run clean-mac + clean-pyc"
	@echo ""

# ── Stack ─────────────────────────────────────────────────────────────────────

.PHONY: build
build: clean-mac
	$(COMPOSE) build

.PHONY: up
up: clean-mac
	$(COMPOSE) up -d

.PHONY: down
down:
	$(COMPOSE) down

.PHONY: stop
stop:
	$(COMPOSE) stop

.PHONY: start
start:
	$(COMPOSE) start

.PHONY: restart
restart: stop start

.PHONY: reset
reset:
	@echo "WARNING: This will delete all containers AND volumes (database, workspace, logs)."
	@read -r -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] || (echo "Aborted."; exit 1)
	$(COMPOSE) down -v

# ── Logs & status ─────────────────────────────────────────────────────────────

.PHONY: ps
ps:
	$(COMPOSE) ps

.PHONY: logs
logs:
	$(COMPOSE) logs -f

.PHONY: logs-web
logs-web:
	$(COMPOSE) logs -f web

.PHONY: logs-worker
logs-worker:
	$(COMPOSE) logs -f celery_worker

.PHONY: logs-beat
logs-beat:
	$(COMPOSE) logs -f celery_beat

# ── Django ────────────────────────────────────────────────────────────────────

.PHONY: migrate
migrate:
	$(MANAGE) migrate

.PHONY: makemigrations
makemigrations:
	$(MANAGE) makemigrations

.PHONY: superuser
superuser:
	$(MANAGE) createsuperuser

.PHONY: shell
shell:
	$(MANAGE) shell

.PHONY: bash
bash:
	$(COMPOSE) exec $(APP) bash

.PHONY: collectstatic
collectstatic:
	$(MANAGE) collectstatic --noinput

# ── Testing (runs locally, not inside the production image) ───────────────────

.PHONY: test
test:
	python -m pytest

.PHONY: test-fast
test-fast:
	python -m pytest -x --tb=short

.PHONY: test-cov
test-cov:
	python -m pytest --tb=short --cov=. --cov-report=term-missing

# ── Utilities ─────────────────────────────────────────────────────────────────

.PHONY: clean-mac
clean-mac:
	@find . -name '._*' -not -path './.git/*' -delete 2>/dev/null && \
		echo "Removed macOS ._* files." || true

.PHONY: clean-pyc
clean-pyc:
	@find . -type f -name '*.pyc' -delete && \
	 find . -type d -name '__pycache__' -delete && \
	 echo "Removed .pyc and __pycache__."

.PHONY: clean
clean: clean-mac clean-pyc
