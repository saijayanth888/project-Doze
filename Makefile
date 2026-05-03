.PHONY: help dev db-only api frontend up down build logs logs-api install install-dev clean health pull-model n8n-open dashboard-open test lint format

PYTHON ?= python3.13
VENV   ?= .venv

help:
	@echo "ModelForge — make targets"
	@echo "  install        Create $(VENV) (Python 3.13) and install runtime deps"
	@echo "  install-dev    Same as install + dev tooling (pytest, ruff, mypy)"
	@echo "  db-only        Bring up postgres + redis + n8n only"
	@echo "  api            Run FastAPI in foreground with reload"
	@echo "  frontend       Run Vite dev server in foreground"
	@echo "  up             docker compose up -d (cpu profile)"
	@echo "  up-gpu         docker compose --profile gpu up -d"
	@echo "  down           docker compose down"
	@echo "  build          docker compose build"
	@echo "  test           pytest"
	@echo "  lint           ruff + mypy"
	@echo "  health         curl /api/system/health"

# ── Setup ─────────────────────────────────────────────────
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	cd frontend && npm install

install-dev: install
	$(VENV)/bin/pip install -r requirements-dev.txt

# ── Local dev (run in two terminals) ──────────────────────
db-only:
	docker compose up -d postgres redis n8n

api:
	$(VENV)/bin/uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000 --reload --reload-dir src

frontend:
	cd frontend && npm run dev

# ── Docker stack ──────────────────────────────────────────
up:
	docker compose up -d

up-gpu:
	docker compose --profile gpu up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f --tail=100

logs-api:
	docker compose logs -f api --tail=100

# ── Tests + lint ──────────────────────────────────────────
test:
	$(VENV)/bin/pytest

lint:
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/mypy src

format:
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests

# ── Utilities ─────────────────────────────────────────────
pull-model:
	@read -p "Model tag (e.g. llama3.2:3b): " model; \
	curl -X POST http://localhost:11434/api/pull -d "{\"name\":\"$$model\"}"

health:
	@curl -s -H "X-API-Key: $${MODELFORGE_API_KEY:-}" http://localhost:8000/api/system/health | $(PYTHON) -m json.tool

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

n8n-open:
	open http://localhost:5678

dashboard-open:
	open http://localhost:3000
