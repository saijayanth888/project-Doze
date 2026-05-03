#!/usr/bin/env bash
# Wait for n8n to become healthy, print login hints, then try REST owner bootstrap.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

N8N_URL="${N8N_URL:-http://localhost:5678}"
echo "Waiting for n8n at ${N8N_URL}/healthz …"
for _ in $(seq 1 60); do
  if curl -fsS "${N8N_URL}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " n8n is up"
echo "═══════════════════════════════════════════════════════════"
echo "  UI URL:           ${N8N_URL}"
echo "  Basic auth user:  ${N8N_BASIC_AUTH_USER:-admin}"
echo "  Owner email:      ${N8N_OWNER_EMAIL:-${N8N_EMAIL:-admin@modelforge.local}}"
echo ""
echo "  Import workflows:  integrations/n8n/workflows/*.json"
echo "  Webhook (evolve):  ${N8N_WEBHOOK_URL:-http://localhost:5678/}webhook/evolution-events"
echo ""

export N8N_URL
export N8N_BASIC_AUTH_USER="${N8N_BASIC_AUTH_USER:-admin}"
export N8N_BASIC_AUTH_PASSWORD="${N8N_BASIC_AUTH_PASSWORD:?set N8N_BASIC_AUTH_PASSWORD in .env}"
export N8N_OWNER_EMAIL="${N8N_OWNER_EMAIL:-${N8N_EMAIL:-admin@modelforge.local}}"
export N8N_OWNER_PASSWORD="${N8N_OWNER_PASSWORD:-$N8N_BASIC_AUTH_PASSWORD}"

PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

"${PYTHON}" "${ROOT}/scripts/n8n_bootstrap_owner.py" || true

echo ""
echo "Done. Log in through the browser (Basic Auth dialog, then n8n owner if prompted)."
