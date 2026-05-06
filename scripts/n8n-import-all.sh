#!/usr/bin/env bash
# Import all workflows from integrations/n8n/workflows/ into n8n and sync active state.
#
# Delegates to scripts/n8n_import_workflows.py (httpx):
#   - With N8N_API_KEY: public API /api/v1/workflows
#   - Otherwise: /rest/login session + internal /rest/workflows (session cookies do NOT
#     authenticate /api/v1 — that caused 401 when this logic lived only in bash + /api/v1).
#
# Requires: Python 3 + httpx (see apps/api/requirements.txt / make install).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

exec "$PYTHON" "${ROOT}/scripts/n8n_import_workflows.py" "$@"
