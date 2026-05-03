#!/usr/bin/env bash
# Wipe n8n filesystem cache + Postgres "n8n" DB, recreate DB, start n8n, run owner bootstrap.
# Requires: docker compose stack from this repo; httpx for bootstrap (API venv or pip install httpx).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-modelforge}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-mf-postgres}"
N8N_CONTAINER="${N8N_CONTAINER:-mf-n8n}"

echo "This will permanently delete:"
echo "  - Docker volume backing /home/node/.n8n for ${N8N_CONTAINER}"
echo "  - PostgreSQL database named n8n (workflows, credentials, execution data)"
echo "  - The ${N8N_CONTAINER} container (recreated by compose)"
echo ""
read -r -p "Type YES to continue: " confirm
[[ "${confirm:-}" == "YES" ]] || { echo "Aborted."; exit 1; }

if ! docker inspect "${POSTGRES_CONTAINER}" &>/dev/null; then
  echo "Postgres container ${POSTGRES_CONTAINER} not found. Start the stack first: docker compose up -d postgres" >&2
  exit 1
fi

echo "Stopping n8n…"
docker compose stop n8n 2>/dev/null || true

VOL=""
if docker inspect "${N8N_CONTAINER}" &>/dev/null; then
  VOL="$(docker inspect "${N8N_CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/home/node/.n8n"}}{{.Name}}{{end}}{{end}}')"
fi
docker rm -f "${N8N_CONTAINER}" 2>/dev/null || true

if [[ -n "${VOL}" ]]; then
  echo "Removing volume ${VOL}…"
  docker volume rm -f "${VOL}" || true
fi

echo "Dropping and recreating database n8n…"
docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 <<EOSQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'n8n' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS n8n;
CREATE DATABASE n8n OWNER "${POSTGRES_USER}";
EOSQL

docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d n8n -v ON_ERROR_STOP=1 -c \
  "GRANT ALL ON SCHEMA public TO \"${POSTGRES_USER}\"; ALTER SCHEMA public OWNER TO \"${POSTGRES_USER}\";"

echo "Starting n8n…"
docker compose up -d n8n

export N8N_BASIC_AUTH_USER="${N8N_BASIC_AUTH_USER:-admin}"
export N8N_BASIC_AUTH_PASSWORD="${N8N_BASIC_AUTH_PASSWORD:?Set N8N_BASIC_AUTH_PASSWORD in .env}"
export N8N_OWNER_EMAIL="${N8N_OWNER_EMAIL:-${N8N_EMAIL:-admin@modelforge.local}}"
export N8N_OWNER_PASSWORD="${N8N_OWNER_PASSWORD:-$N8N_BASIC_AUTH_PASSWORD}"

# Host URL for probes (strip trailing slash from webhook base if N8N_URL unset).
if [[ -z "${N8N_URL:-}" && -n "${N8N_WEBHOOK_URL:-}" ]]; then
  export N8N_URL="${N8N_WEBHOOK_URL%/}"
fi
export N8N_URL="${N8N_URL:-http://localhost:5678}"

echo "Waiting for n8n health + bootstrapping owner (${N8N_OWNER_EMAIL})…"
exec "${ROOT}/scripts/n8n-wait-and-login.sh"
