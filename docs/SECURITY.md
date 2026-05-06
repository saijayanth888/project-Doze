# Security model

ModelForge is designed for **single-tenant private deployment** behind
an authenticated reverse proxy. It is not a multi-tenant SaaS; the
threat model below reflects that.

## Threat model

| In scope                                            | Out of scope                                          |
| --------------------------------------------------- | ----------------------------------------------------- |
| Stolen / leaked API keys                            | Multi-user RBAC, SSO, OIDC                            |
| Network attackers between SPA ↔ API                 | Side-channel attacks on shared GPU hardware           |
| Misconfigured CORS exposing the API to any origin   | Supply-chain attacks on Hugging Face model weights    |
| Internal services reachable from outside the host  | Insider threats on the DGX host                       |
| n8n / vLLM / Ollama unauthenticated public exposure | Adversarial inputs that poison evolved adapters       |

## Controls in this repo

### API authentication

- Every `/api/*` and `/api/ws/*` route requires `X-API-Key`.
- Allowlist: `/api/system/health`, `/api/system/status`, `/docs`,
  `/redoc`, `/openapi.json`, `/favicon.ico`.
- `MODELFORGE_API_KEY` is **mandatory** when `ENVIRONMENT=production` —
  startup fails if it's missing.
- WebSocket clients pass the key as `?api_key=...` because browsers
  can't set headers on `new WebSocket(...)`.
- Comparison uses `hmac.compare_digest` to avoid timing attacks.

### Transport hardening

- `SecurityHeadersMiddleware` emits:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), microphone=(), camera=()`
  - `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
    (only when the request arrived over HTTPS).
- Nginx mirrors all of the above at the edge.

### CORS

- `CORS_ORIGINS` is a comma-separated allowlist.
- If `*` is present, `allow_credentials` is forced to `False` to comply
  with the CORS spec — browsers reject the wildcard-with-credentials
  combination.
- Production deployments **must** list explicit origins.

### Network isolation

- **Ollama:** Often runs on the **host** (systemd), not in Docker. The API
  container uses `OLLAMA_HOST` (default `http://host.docker.internal:11434`)
  to call the host’s Ollama HTTP API. No Ollama container is required.
  If you opt into the optional Compose `ollama` service (`profiles: ["gpu"]`),
  set `OLLAMA_HOST=http://ollama:11434` instead.
- **vLLM** is tagged `profiles: ["gpu"]` and only exposes port 8000 on the
  internal Docker network (`expose:` instead of `ports:`). The API reaches
  it at `http://vllm:8000` (or your `VLLM_HOST`).
- vLLM **requires** `VLLM_API_KEY` (no `:-none` fallback) — Compose
  refuses to start the `gpu` profile without it.
- n8n basic auth is enabled by default; `N8N_BASIC_AUTH_PASSWORD` is
  required.

### Database

- Postgres password is required (no fallback).
- Schema is bootstrapped via `scripts/init_db.sql` and the runtime
  `_SCHEMA_STATEMENTS` — both are idempotent (`CREATE TABLE IF NOT EXISTS`).
- pgvector extension is created on first boot.

## Rotation playbook

| Secret                       | How to rotate                                               |
| ---------------------------- | ----------------------------------------------------------- |
| `MODELFORGE_API_KEY`         | Update `.env`, restart `api`, distribute new key to clients |
| `POSTGRES_PASSWORD`          | `ALTER USER` in Postgres, update `.env`, restart `api`      |
| `N8N_BASIC_AUTH_PASSWORD`    | Update `.env`, restart `n8n` (sessions invalidated)         |
| `VLLM_API_KEY`               | Update `.env`, restart `vllm` and `api`                     |
| `HF_TOKEN`                   | Re-issue on hf.co, update `.env`, restart `vllm`            |

## Reporting

Email security findings privately to the repo owner. Do **not** open a
public issue.
