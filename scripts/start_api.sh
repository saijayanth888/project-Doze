#!/usr/bin/env bash
# Start the ModelForge FastAPI server (from the repo root) for local dev.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "Starting ModelForge API on http://0.0.0.0:8000 ..."
echo "Swagger UI: http://localhost:8000/docs"
echo ""

exec uvicorn main:app \
  --app-dir src \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --reload-dir src
