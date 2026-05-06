.PHONY: help dev db-only api frontend up down build logs logs-api install install-dev clean health pull-model n8n-open dashboard-open test lint format test-e2e test-e2e-spark n8n-bootstrap first-run

PYTHON ?= python3.13
VENV   ?= .venv
API_DIR = apps/api
WEB_DIR = apps/web/frontend

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
	@echo "  test           pytest (apps/api)"
	@echo "  test-e2e       Playwright against default baseURL (often localhost — dev)"
	@echo "  test-e2e-spark Playwright Spark suite (LAN_IP from .env; API via :3001 unless API_URL set)"
	@echo "  first-run       Pre-flight checks + POST /api/evolve/start (uses scripts/start_first_evolution.sh)"
	@echo "  n8n-bootstrap  Wait for n8n + create owner via REST (see .env)"
	@echo "  lint           ruff + mypy"
	@echo "  health         curl /api/system/health"

# ── Setup ─────────────────────────────────────────────────
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r $(API_DIR)/requirements.txt
	cd $(WEB_DIR) && npm install

install-dev: install
	$(VENV)/bin/pip install -r $(API_DIR)/requirements-dev.txt

# ── Local dev (run in two terminals) ──────────────────────
db-only:
	docker compose up -d postgres redis n8n

api:
	$(VENV)/bin/uvicorn main:app --app-dir $(API_DIR)/src --host 0.0.0.0 --port 8000 --reload --reload-dir $(API_DIR)/src

frontend:
	cd $(WEB_DIR) && npm run dev

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
	cd $(API_DIR) && ../../$(VENV)/bin/pytest tests

lint:
	cd $(API_DIR) && ../../$(VENV)/bin/ruff check src tests
	cd $(API_DIR) && ../../$(VENV)/bin/mypy src

format:
	cd $(API_DIR) && ../../$(VENV)/bin/ruff format src tests
	cd $(API_DIR) && ../../$(VENV)/bin/ruff check --fix src tests

test-e2e:
	cd $(WEB_DIR) && npx playwright install --with-deps
	cd $(WEB_DIR) && npm run test:e2e

# Uses PLAYWRIGHT_BASE_URL=http://$LAN_IP:3001 — run on the Spark host after `docker compose --profile gpu up -d`.
test-e2e-spark:
	@test -f .env || (echo "Missing .env — copy .env.example and set LAN_IP=" >&2; exit 1)
	set -a && . ./.env && set +a && \
	IP="$${LAN_IP:-192.168.1.49}" && \
	cd $(WEB_DIR) && \
	SPARK_IP="$$IP" PLAYWRIGHT_BASE_URL="http://$$IP:3001" \
	N8N_URL="http://$$IP:5679" CI=1 \
	npx playwright test e2e/spark-e2e.spec.ts --reporter=list

first-run:
	chmod +x scripts/start_first_evolution.sh
	bash scripts/start_first_evolution.sh

n8n-bootstrap:
	chmod +x scripts/n8n-wait-and-login.sh
	./scripts/n8n-wait-and-login.sh

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
	open http://localhost:$${MODELFORGE_WEB_HOST_PORT:-3001}
