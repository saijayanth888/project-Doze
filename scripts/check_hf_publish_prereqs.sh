#!/usr/bin/env bash
# Pre-flight check for the `adapter.publish_huggingface` workflow.
#
# Confirms HF_TOKEN authenticates against the Hub and that the target
# private repo exists. The action degrades gracefully on its own (skipped
# vs error), but running this once after editing .env is cheaper than
# waiting for a track.promoted event to expose a misconfiguration.
#
# Exit codes:
#   0  -- token valid AND target repo exists
#   1  -- HF_TOKEN not set
#   2  -- token rejected by whoami-v2 (HTTP 401/403)
#   3  -- target repo does not exist (HTTP 404)
#   4  -- unexpected HTTP error from the Hub
#
# Usage:
#   ./scripts/check_hf_publish_prereqs.sh
#   HF_REPO_ID=Saijayanyh532ai/dgx-trader-adapters ./scripts/check_hf_publish_prereqs.sh
#
# Honors .env in the model-forge root: this script sources it (if present)
# so the operator doesn't have to re-export HF_TOKEN by hand.

set -euo pipefail

cyan() { printf "\033[36m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red() { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

# 1. Load .env if present (without leaking it into the shell history).
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  set +a
fi

HF_REPO_ID="${HF_REPO_ID:-Saijayanyh532ai/dgx-trader-adapters}"

cyan "Pre-flight: adapter.publish_huggingface"
echo "  repo id : ${HF_REPO_ID}"
echo "  token   : $([[ -n "${HF_TOKEN:-}" ]] && echo '<set>' || echo '<missing>')"
echo

# 2. Token must be set.
if [[ -z "${HF_TOKEN:-}" ]]; then
  red "[fail] HF_TOKEN not set in ${ROOT}/.env or current shell."
  echo "       Add HF_TOKEN=hf_xxx (write-scope) to ${ROOT}/.env"
  exit 1
fi

# 3. whoami-v2 confirms the token is valid (auth + read scope).
cyan "Calling whoami-v2 ..."
WHOAMI_HTTP="$(curl --silent --show-error --max-time 10 \
  -o /tmp/_hf_whoami.json -w '%{http_code}' \
  -H "Authorization: Bearer ${HF_TOKEN}" \
  https://huggingface.co/api/whoami-v2 || echo "000")"

case "${WHOAMI_HTTP}" in
  200)
    USERNAME="$(python3 -c 'import json,sys; print(json.load(open("/tmp/_hf_whoami.json")).get("name","?"))')"
    green "[ok]   authenticated as ${USERNAME}"
    ;;
  401|403)
    red "[fail] HF_TOKEN rejected (HTTP ${WHOAMI_HTTP})."
    echo "       Regenerate at https://huggingface.co/settings/tokens (write scope)"
    exit 2
    ;;
  *)
    red "[fail] whoami-v2 returned HTTP ${WHOAMI_HTTP}"
    cat /tmp/_hf_whoami.json
    exit 4
    ;;
esac

# 4. Confirm the target repo exists. The API returns 401 instead of 404
#    for private repos when no token is sent — so the header is required
#    even for the existence probe.
echo
cyan "Checking target repo ${HF_REPO_ID} ..."
REPO_HTTP="$(curl --silent --show-error --max-time 10 \
  -o /tmp/_hf_repo.json -w '%{http_code}' \
  -H "Authorization: Bearer ${HF_TOKEN}" \
  "https://huggingface.co/api/models/${HF_REPO_ID}" || echo "000")"

case "${REPO_HTTP}" in
  200)
    IS_PRIVATE="$(python3 -c 'import json,sys; print(json.load(open("/tmp/_hf_repo.json")).get("private",False))')"
    green "[ok]   repo exists (private=${IS_PRIVATE})"
    ;;
  404)
    red "[fail] repo not found: ${HF_REPO_ID}"
    echo "       Create it at https://huggingface.co/new (private, model type)"
    exit 3
    ;;
  401|403)
    red "[fail] token has no read access on ${HF_REPO_ID} (HTTP ${REPO_HTTP})"
    echo "       Either the repo isn't owned by this token's user, or the"
    echo "       token lacks read+write scope. Regenerate with full scope."
    exit 2
    ;;
  *)
    red "[fail] repo probe returned HTTP ${REPO_HTTP}"
    cat /tmp/_hf_repo.json
    exit 4
    ;;
esac

echo
green "Pre-flight passed. The next track.promoted event for a trading-* track"
green "will mirror the adapter dir to ${HF_REPO_ID}@<track_id>-v<YYYYMMDD>."
exit 0
