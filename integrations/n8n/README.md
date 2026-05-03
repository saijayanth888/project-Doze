# n8n integration

Workflow JSON exports live in [`workflows/`](workflows/). They are wired for **Docker Compose networking**:

| Endpoint | URL inside containers |
| -------- | --------------------- |
| FastAPI  | `http://api:8000`     |
| n8n UI   | `http://localhost:5679` (Compose default host port → container `5678`) |

## Prerequisites

1. **PostgreSQL** — n8n uses database `n8n` on the shared Postgres service (same `POSTGRES_USER` / `POSTGRES_PASSWORD` as ModelForge). Created automatically by `scripts/postgres-init/02-n8n-database.sql`.

2. **Environment variables** (set in root `.env` and passed through `docker-compose.yml`):

   | Variable | Purpose |
   | -------- | ------- |
   | `N8N_ENCRYPTION_KEY` | **Required.** 32+ random chars (`openssl rand -hex 32`). |
   | `MODELFORGE_API_KEY` | Sent as `X-API-Key` from HTTP Request nodes (`$env.MODELFORGE_API_KEY`). |
   | `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` | Reverse-proxy style protection for the editor. |
   | `SLACK_WEBHOOK_URL` | Optional. Slack nodes use `={{ $env.SLACK_WEBHOOK_URL }}`. |
   | `N8N_WEBHOOK_EVOLUTION_URL` | Set on the **API** container — target for evolution events (`http://n8n:5678/webhook/evolution-events`). |

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
| `evolution-monitor.json` | Webhook `POST /webhook/evolution-events` — routes `generation_complete`, `champion_promoted`, `run_complete`, `error`. |
| `evolution-scheduler.json` | Every 6h: if GPU available, `POST /api/evolve/start` with `X-API-Key`. |
| `health-check-monitor.json` | Every 15m: `GET /api/system/health`, expects `status === ok`, posts failures to `/api/system/alerts`. |

## FastAPI → n8n

The LangGraph runner calls `N8N_WEBHOOK_EVOLUTION_URL` after each generation decision and on run completion / failure. Payload fields match the Evolution Monitor switch (`event_type`, `run_id`, `generation_number`, scores, etc.).

## Importing

1. Open n8n → **Workflows** → **Import from File**.
2. Select each JSON under `integrations/n8n/workflows/`.
3. **Activate** workflows and confirm webhook URLs match your `WEBHOOK_URL` base.

## Production checklist

1. **Public URL** — Set `N8N_WEBHOOK_URL` / `WEBHOOK_URL` to the HTTPS origin users and the API will use (same host you expose for webhooks). Must match the editor **Settings → Public URL** behavior so copied webhook URLs are correct.
2. **Secrets** — Use strong `N8N_ENCRYPTION_KEY`, `N8N_BASIC_AUTH_*`, and `MODELFORGE_API_KEY`. Never commit real values; inject via your orchestrator or secret manager.
3. **Evolution webhook** — In **Evolution Monitor**, tighten **Webhook → Options → Allowed Origins** from `*` to your API origin (or remove browser-only testing origins) so only your FastAPI host can POST in environments where that matters.
4. **API → n8n** — `N8N_WEBHOOK_EVOLUTION_URL` on the API service must stay on the **Docker internal** URL (`http://n8n:5678/webhook/evolution-events`); only the **public** `WEBHOOK_URL` changes for link generation.
5. **Smoke-test webhook** (replace host if needed):

   ```bash
   curl -sS -X POST "http://localhost:5679/webhook/evolution-events" \
     -H "Content-Type: application/json" \
     -d '{"event_type":"run_complete","run_id":"e2e-smoke","generation_number":0}'
   ```

   Expect **202** once the workflow is **active** and the webhook path is registered.
