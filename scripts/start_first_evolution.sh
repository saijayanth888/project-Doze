#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# ModelForge — First Evolution Run
# ═══════════════════════════════════════════════════════

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env in $ROOT — copy .env.example and set MODELFORGE_API_KEY" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

API_KEY="${MODELFORGE_API_KEY:-}"
API_URL="${API_URL:-http://localhost:8000}"

if [[ -z "$API_KEY" ]]; then
  echo "MODELFORGE_API_KEY is not set in .env" >&2
  exit 1
fi

json_get() {
  local key="$1"
  if command -v jq &>/dev/null; then
    jq -r "$key"
  else
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d${key#})" 2>/dev/null
  fi
}

echo "🧬 ModelForge — Starting First Evolution Run"
echo "════════════════════════════════════════════"
echo ""
echo "Pre-flight checks (API: $API_URL):"
echo -n "  API health: "
HEALTH_JSON=$(curl -sf -H "X-API-Key: $API_KEY" "$API_URL/api/system/health" || true)
if [[ -z "$HEALTH_JSON" ]]; then
  echo "❌ unreachable"
  exit 1
fi
if command -v jq &>/dev/null; then
  HEALTH=$(echo "$HEALTH_JSON" | jq -r '.status')
  PG=$(echo "$HEALTH_JSON" | jq -r '.postgres')
else
  HEALTH=$(echo "$HEALTH_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))")
  PG=$(echo "$HEALTH_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('postgres',''))")
fi
[[ "$HEALTH" == "ok" || "$HEALTH" == "degraded" ]] && echo "✅ $HEALTH (postgres: $PG)" || { echo "❌ $HEALTH"; exit 1; }

echo -n "  GPU status: "
GPU_JSON=$(curl -sf -H "X-API-Key: $API_KEY" "$API_URL/api/system/gpu" || true)
if [[ -n "$GPU_JSON" ]]; then
  if command -v jq &>/dev/null; then
    GPU=$(echo "$GPU_JSON" | jq -r '.gpu_available')
  else
    GPU=$(echo "$GPU_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('gpu_available'))")
  fi
  echo "$GPU"
else
  echo "(skipped)"
fi

echo ""
echo "Testing inference (Ollama)..."
INFER_JSON=$(curl -sf -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  "$API_URL/api/infer" \
  -d '{"prompt": "Say hello in 3 words", "max_tokens": 20}' || true)
if [[ -z "$INFER_JSON" ]]; then
  echo "  ❌ Inference failed — check Ollama"
  exit 1
fi
if command -v jq &>/dev/null; then
  INFER=$(echo "$INFER_JSON" | jq -r '.response // empty')
else
  INFER=$(echo "$INFER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('response') or '')")
fi
echo "  Ollama says: $INFER"
if [[ -z "$INFER" ]]; then
  echo "  ❌ Empty response"
  exit 1
fi
echo "  ✅ Inference working"

echo ""
echo "════════════════════════════════════════════"
echo "Starting evolution run..."
echo "  Model:       llama3.2:3b (small for first test)"
echo "  Generations: 1 (proof of concept)"
echo "════════════════════════════════════════════"
echo ""

RESULT=$(curl -sf -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  "$API_URL/api/evolve/start" \
  -d '{"base_model":"llama3.2:3b","max_generations":1}')

if command -v jq &>/dev/null; then
  RUN_ID=$(echo "$RESULT" | jq -r '.run_id // empty')
  STATUS=$(echo "$RESULT" | jq -r '.status // empty')
else
  RUN_ID=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('run_id') or '')")
  STATUS=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status') or '')")
fi

echo "Run ID:  $RUN_ID"
echo "Status:  $STATUS"
echo ""

if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
  echo "❌ Failed to start evolution"
  echo "Response: $RESULT"
  exit 1
fi

echo "🚀 Evolution started!"
echo ""
echo "Monitor with:"
echo "  docker compose logs -f api"
echo "  curl -H 'X-API-Key: ****' $API_URL/api/evolve/status"
LAN="${LAN_IP:-}"
if [[ -n "$LAN" ]]; then
  echo "  Open http://${LAN}:3001/dashboard"
fi
echo ""
echo "This may take 10–30+ minutes depending on training and eval."
