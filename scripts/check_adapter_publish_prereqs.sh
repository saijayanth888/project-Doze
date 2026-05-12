#!/usr/bin/env bash
# Pre-flight check for the `adapter.publish_ollama` workflow.
#
# Confirms the host Ollama is reachable from inside the mf-api container
# (the same network position the action runs from), and prints the
# current model list so the operator can spot-check the baseline before
# the first trading-* track promotion lands.
#
# Exit codes:
#   0  -- Ollama reachable, baseline printed
#   1  -- api container not running (start with `docker compose up`)
#   2  -- Ollama unreachable from inside the api container
#   3  -- unexpected curl error
#
# Usage:
#   ./scripts/check_adapter_publish_prereqs.sh
#   OLLAMA_BASE=http://ollama:11434 ./scripts/check_adapter_publish_prereqs.sh

set -euo pipefail

OLLAMA_BASE="${OLLAMA_BASE:-http://host.docker.internal:11434}"
CONTAINER="${MF_API_CONTAINER:-mf-api}"

cyan() { printf "\033[36m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red() { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }

cyan "Pre-flight: adapter.publish_ollama"
echo "  api container : ${CONTAINER}"
echo "  ollama base   : ${OLLAMA_BASE}"
echo

# 1. Container must be running.
if ! docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' \
     | grep -q "^${CONTAINER}$"; then
  red "[fail] container '${CONTAINER}' is not running."
  echo "       Start it with: docker compose up -d api"
  exit 1
fi
green "[ok]   container '${CONTAINER}' is running"

# 2. Ping /api/tags from inside the container.
echo
cyan "Probing ${OLLAMA_BASE}/api/tags from inside ${CONTAINER} ..."
TAGS_JSON="$(
  docker exec "${CONTAINER}" \
    curl --silent --show-error --max-time 5 \
         --fail "${OLLAMA_BASE}/api/tags" 2>&1 || true
)"

if [[ -z "${TAGS_JSON}" ]] || ! echo "${TAGS_JSON}" | grep -q '"models"'; then
  red "[fail] Ollama unreachable at ${OLLAMA_BASE} from inside ${CONTAINER}."
  echo "       Response was:"
  echo "       ${TAGS_JSON}"
  echo
  yellow "Diagnosis hints:"
  echo "  - On the host: systemctl status ollama  (or:  ollama serve &)"
  echo "  - Ensure ollama is listening on 0.0.0.0, not just 127.0.0.1"
  echo "    (export OLLAMA_HOST=0.0.0.0:11434 before launching the daemon)"
  echo "  - docker-compose.yml api block needs: extra_hosts: [host.docker.internal:host-gateway]"
  exit 2
fi
green "[ok]   /api/tags responded"

# 3. Pretty-print the baseline model list (or 'none' if empty).
echo
cyan "Current Ollama models (baseline before first trading-* publish):"
echo "${TAGS_JSON}" | python3 -c '
import json, sys
data = json.load(sys.stdin)
models = data.get("models") or []
if not models:
    print("  (none)")
else:
    for m in models:
        name = m.get("name") or m.get("model") or "?"
        size_b = m.get("size") or 0
        size_gb = (float(size_b) / 1e9) if size_b else 0.0
        print(f"  - {name:60s} {size_gb:6.2f} GB")
'

echo
green "Pre-flight passed. The next track.promoted event for a trading-* track"
green "will publish a qwen3-30b-<role>-v<YYYYMMDD> model + alias."
exit 0
