#!/usr/bin/env bash
# Import bundled workflows into the n8n container via the official CLI (no UI, no REST session).
# Requires: docker compose from repo root; n8n service running; volume mount in docker-compose.yml.
#
# Skips if "Evolution Monitor" already appears in `n8n list:workflow` (avoids duplicate stacks on re-run).
# Set N8N_REIMPORT_BUNDLED_WORKFLOWS=1 to import anyway.
# Set N8N_SKIP_WORKFLOW_IMPORT=1 to no-op.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ "${N8N_SKIP_WORKFLOW_IMPORT:-}" =~ ^(1|true|yes)$ ]]; then
  echo "N8N_SKIP_WORKFLOW_IMPORT set — skipping bundled workflow import."
  exit 0
fi

if ! docker compose ps -q n8n 2>/dev/null | grep -q .; then
  echo "n8n service is not running — skipping bundled workflow import." >&2
  exit 0
fi

IMPORT_DIR=/import/modelforge-workflows
if ! docker compose exec -T -u node n8n test -d "$IMPORT_DIR" 2>/dev/null; then
  echo "Missing $IMPORT_DIR in n8n container — rebuild stack after pulling latest compose (workflows volume)." >&2
  exit 1
fi

if [[ ! "${N8N_REIMPORT_BUNDLED_WORKFLOWS:-}" =~ ^(1|true|yes)$ ]]; then
  if docker compose exec -T -u node n8n n8n list:workflow 2>/dev/null | grep -q '|Evolution Monitor'; then
    echo "Bundled workflows already present (Evolution Monitor found). Skipping import."
    echo "  To import again: N8N_REIMPORT_BUNDLED_WORKFLOWS=1 $0"
    exit 0
  fi
fi

echo "Importing bundled workflows from ${IMPORT_DIR} …"
docker compose exec -T -u node n8n n8n import:workflow --separate --input="$IMPORT_DIR"
echo "Done. Activate workflows in the n8n UI if they were imported inactive."
