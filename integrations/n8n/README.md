# n8n integration

Workflow JSON exports live in [`workflows/`](workflows/) (canonical copy for Compose and MCP). They are wired for **Docker Compose networking**:

> **Note:** A duplicate tree may exist at repo root `n8n/workflows/` from older copies — prefer **`integrations/n8n/workflows/`** for imports and automation.

## Cursor MCP (validate & inspect workflows)

Use n8n’s **instance-level MCP** so Cursor can call tools such as `search_workflows`, `get_workflow_details`, `validate_workflow` (Workflow SDK source), and `execute_workflow`.

1. In n8n: **Settings → Instance-level MCP** → enable MCP → **Connection details** → **Access Token** tab → copy your token (store only in local config, not in git).
2. In this repo: `cp .cursor/mcp.json.example .cursor/mcp.json` and edit:
   - **`url`**: same origin as your browser n8n URL, path **`/mcp-server/http`** (no trailing slash on the origin), e.g. `http://localhost:5679/mcp-server/http` if `N8N_HOST_PORT=5679`.
   - **`Authorization`**: `Bearer <token>` from step 1.
3. Restart Cursor (or reload MCP) so the server registers.
4. For each workflow the agent should run or inspect in depth, enable **Available in MCP** (workflow **…** menu → Settings, or the Instance-level MCP workflows table). `search_workflows` can still list previews of others.

**Security:** If a token was pasted into chat or committed by mistake, rotate it in n8n (generate a new MCP access token) and update `.cursor/mcp.json` only.

Official reference: [Accessing n8n MCP server](https://docs.n8n.io/advanced-ai/mcp/accessing-n8n-mcp-server/) and [MCP tools reference](https://docs.n8n.io/advanced-ai/mcp/mcp_tools_reference/).

### Hardening & validation (repo scripts)

- **`python3 scripts/harden_n8n_workflow_exports.py`** — strips instance-specific export fields, sets workflow descriptions, tightens webhook CORS, HTTP timeouts, and `saveManualExecutions: false` on bundled workflows. Run after re-exporting from the n8n UI.
- **`python3 scripts/validate_n8n_workflow_bundle.py`** — static JSON checks (structure + obvious secret patterns); safe for **CI** without a running n8n instance.
- **Live MCP** (`validate_workflow`, `get_workflow_details`, …) requires your Cursor client to connect to n8n per `.cursor/mcp.json.example`; that validation runs in **your** IDE, not in GitHub Actions.

| Endpoint | URL inside containers |
| -------- | --------------------- |
| FastAPI  | `http://api:8000`     |
| n8n UI (browser) | `http://localhost:5679` by default (`N8N_HOST_PORT` → container **5678**; internal DNS remains `n8n:5678`) |

## Hard reset (wipe workflows + owner, re-bootstrap)

Use when the editor is stuck, credentials are unknown, or health checks never go green after a bad migration.

1. Set in `.env` (same values you will use in the browser): `N8N_BASIC_AUTH_USER` (default `admin`), `N8N_BASIC_AUTH_PASSWORD`, `N8N_OWNER_EMAIL`, `N8N_OWNER_PASSWORD` (often match basic auth for dev), and keep `N8N_ENCRYPTION_KEY` stable unless you intend a full credential re-import.
2. From repo root:

   ```bash
   chmod +x scripts/n8n-reset-and-reseed.sh
   ./scripts/n8n-reset-and-reseed.sh
   ```

3. Open the UI at `N8N_WEBHOOK_URL` without the trailing path (e.g. `http://localhost:5679`). Complete Basic Auth, then sign in as the owner email.

If `docker ps` shows **two** host bindings for n8n (e.g. both **5678** and **5679**), your **`docker-compose.override.yml`** likely adds a second `ports` entry; Compose merges lists. Remove the extra `ports` block and use only **`N8N_HOST_PORT`** in `.env`.

## Prerequisites

1. **PostgreSQL** — n8n uses database `n8n` on the shared Postgres service (same `POSTGRES_USER` / `POSTGRES_PASSWORD` as ModelForge). Created automatically by `scripts/postgres-init/02-n8n-database.sql`.

2. **Environment variables** (set in root `.env` and passed through `docker-compose.yml`):

   | Variable | Purpose |
   | -------- | ------- |
   | `N8N_IMAGE` | Optional. Docker image for the n8n service (Compose default: `n8nio/n8n:latest`). Pin a version for reproducible upgrades. |
| `N8N_HOST_PORT` | Optional. Host port mapped to n8n’s **5678** in the container (Compose default **5679** so host **5678** stays free). Use this instead of a second `ports:` entry in `docker-compose.override.yml` — Compose **merges** port lists and would publish two host ports. |
   | `N8N_ENCRYPTION_KEY` | **Required.** 32+ random chars (`openssl rand -hex 32`). |
   | `MODELFORGE_API_KEY` | Sent as `X-API-Key` from HTTP Request nodes (`$env.MODELFORGE_API_KEY`). |
   | `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` | Reverse-proxy style protection for the editor. |
   | `SLACK_WEBHOOK_URL` | Optional. Slack nodes use `={{ $env.SLACK_WEBHOOK_URL }}`. |
   | `N8N_WEBHOOK_EVOLUTION_URL` | Set on the **API** container — target for evolution events (`http://n8n:5678/webhook/evolution-events`). |
| `N8N_WEBHOOK_SECRET` | Optional. API sends `X-Webhook-Signature: sha256=<hmac>` over `event_type|run_id|generation`. Add a **Code** node after the webhook in Evolution Monitor to verify when this is set. |
| `EVOLUTION_BASE_MODEL` / `EVOLUTION_MAX_GENS` | Passed into the **n8n** container for the scheduler’s `POST /api/evolve/start` JSON body. |

3. **Owner account** — after first boot, run:

   ```bash
   chmod +x scripts/n8n-wait-and-login.sh
   ./scripts/n8n-wait-and-login.sh
   ```

   The Python helper needs **httpx** (included in the API venv after `make install-dev`, or `pip install httpx`).

   Or create the owner manually in the browser. Credentials are also documented via `N8N_OWNER_EMAIL` / `N8N_OWNER_PASSWORD` in `.env.example`.

## Workflows

| File | Role |
| ---- | ---- |
| `evolution-monitor.json` | Webhook `POST /webhook/evolution-events` — routes `generation_complete`, `champion_promoted`, `run_complete`, `error`. Response body echoes `event_type` + timestamp. |
| `evolution-scheduler.json` | Every 6h: `GET /api/evolve/status` — skips start when `is_running`; else `GET /api/system/gpu`; if GPU available, `POST /api/evolve/start` with body from `$env.EVOLUTION_BASE_MODEL` / `$env.EVOLUTION_MAX_GENS`. |
| `health-check-monitor.json` | Every 15m: `GET /api/system/health`; healthy branch posts `heartbeat` to `/api/system/alerts`; failures Slack + API alert. |
| `error-handler.json` | **Error workflow** (import, then assign as global error workflow in n8n Settings): `errorTrigger` → `POST /api/system/alerts` with `alert_type: workflow_error`. |

## FastAPI → n8n

The LangGraph runner calls `N8N_WEBHOOK_EVOLUTION_URL` after each generation decision and on run completion / failure. Payload includes `event_type`, `run_id`, `generation` / `generation_number`, `child_scores`, `champion_avg`, `total_generations`, `duration_seconds`, `champion_model_id`, and optional `X-Webhook-Signature` when `N8N_WEBHOOK_SECRET` is set on the API.

## Importing bundled workflows (automated)

On a normal Docker bootstrapping run, **`./scripts/n8n-wait-and-login.sh`** (and **`./scripts/n8n-reset-and-reseed.sh`**, which calls it) runs **`scripts/n8n-import-workflows-compose.sh`** after owner bootstrap. That script uses the official CLI:

`n8n import:workflow --separate --input=/import/modelforge-workflows`

The JSON directory is bind-mounted read-only in `docker-compose.yml`. Import is **skipped** if a workflow named **Evolution Monitor** already exists (avoids duplicates on every script run). To force another CLI import anyway: `N8N_REIMPORT_BUNDLED_WORKFLOWS=1 ./scripts/n8n-import-workflows-compose.sh`.

- Disable all auto-import: `N8N_SKIP_WORKFLOW_IMPORT=1`
- **Idempotent HTTP sync** (PATCH by name): set **`N8N_API_KEY`** from n8n **Settings → API**, then run `python3 scripts/n8n_import_workflows.py` with `N8N_URL` (and basic-auth env vars if the editor is behind basic auth).

## Manual import (UI)

1. Open n8n → **Workflows** → **Import from File**.
2. Select each JSON under `integrations/n8n/workflows/`.
3. **Activate** workflows and confirm webhook URLs match your `WEBHOOK_URL` base.

## Production checklist

1. **Public URL** — Set `N8N_WEBHOOK_URL` / `WEBHOOK_URL` to the HTTPS origin users and the API will use (same host you expose for webhooks). Must match the editor **Settings → Public URL** behavior so copied webhook URLs are correct.
2. **Secrets** — Use strong `N8N_ENCRYPTION_KEY`, `N8N_BASIC_AUTH_*`, and `MODELFORGE_API_KEY`. Never commit real values; inject via your orchestrator or secret manager.
3. **Evolution webhook** — Bundled JSON sets **Allowed Origins** to `http://api:8000` (Docker service name). If your API calls the webhook from another origin or TLS front URL, update the Webhook node options accordingly (or temporarily clear origins for debugging).
4. **API → n8n** — `N8N_WEBHOOK_EVOLUTION_URL` on the API service must stay on the **Docker internal** URL (`http://n8n:5678/webhook/evolution-events`); only the **public** `WEBHOOK_URL` changes for link generation.
5. **Smoke-test webhook** (replace host if needed):

   ```bash
   curl -sS -X POST "http://localhost:5679/webhook/evolution-events" \
     -H "Content-Type: application/json" \
     -d '{"event_type":"run_complete","run_id":"e2e-smoke","generation_number":0}'
   ```

   Expect **202** once the workflow is **active** and the webhook path is registered.

## Optional workflows (build in UI or extend exports)

These are not shipped as JSON (they vary heavily by Slack app / CD URL); sketch them in n8n from the bundled patterns:

- **Weekly digest** — Weekly schedule → `GET /api/lineage/tree` + `GET /api/evolution/generations` → Code (Markdown) → Slack.
- **Slack slash `/infer`** — Slack webhook + signing secret → `POST /api/infer` → Slack response URL.
- **Deployment promotion** — Subscribe to `champion_promoted` (duplicate webhook or sub-workflow) → IF `champion_avg >= $env.PROMOTE_MIN_SCORE` → `POST $env.DEPLOYMENT_HOOK_URL`.
- **Model registry tag** — On `champion_promoted` → `GET /api/models/champion` → annotate external registry (HTTP / your CMDB).

When `N8N_WEBHOOK_SECRET` is set on the API, add a **Code** node immediately after the Evolution Monitor webhook to verify `X-Webhook-Signature`: compute `sha256=HMAC-SHA256(secret, event_type + '|' + run_id + '|' + generation)` and compare to the header (reject with `Respond to Webhook` **401** if mismatch).
