# Deploying ModelForge on DGX Spark

This document covers a single-host production deployment on an NVIDIA
DGX Spark using the `gpu` Compose profile.

## 1. Host prerequisites

- Ubuntu 24.04 LTS (or whatever the DGX Spark ships with).
- Docker Engine **27.x** + `docker compose` plugin.
- NVIDIA driver matching the CUDA your image expects (≥ 550 for
  `vllm/vllm-openai:latest`).
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
  registered with Docker:

  ```bash
  sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
  ```

## 2. Secrets

Generate strong values for every `changeme-*` placeholder in `.env`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'   # MODELFORGE_API_KEY
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # POSTGRES_PASSWORD
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # N8N_BASIC_AUTH_PASSWORD
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # VLLM_API_KEY
```

Then lock the file down:

```bash
chmod 600 .env
sudo chown root:docker .env  # optional, if you want non-root deploy users
```

If you prefer Docker secrets over `.env`:

```yaml
# docker-compose.override.yml
services:
  api:
    secrets:
      - modelforge_api_key
secrets:
  modelforge_api_key:
    file: ./secrets/modelforge_api_key
```

## 3. First boot

```bash
git clone https://github.com/saijayanth888/project-Doze.git
cd project-Doze/model-forge
cp .env.example .env  # then fill in
docker compose --profile gpu up -d --build
```

Postgres bootstraps itself from `scripts/init_db.sql` on first run. The
API container's `HEALTHCHECK` polls `/api/system/status`; verify with:

```bash
docker compose ps
docker compose logs -f api
```

Pre-pull a base model for Ollama:

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

## 4. TLS termination

ModelForge does not handle TLS itself. Front it with **Caddy** for the
simplest setup (it'll pull Let's Encrypt certs automatically):

```Caddyfile
modelforge.example.com {
  reverse_proxy localhost:3000
}
```

Or **Traefik** if you already run one elsewhere on the host. The
backend's `SecurityHeadersMiddleware` will emit `Strict-Transport-Security`
once requests arrive over HTTPS.

## 5. Observability

- `make logs-api` tails the API logs.
- API access logs already include latency (`%.1fms`) per request.
- Recommended: ship logs to Loki/Promtail or Vector. Hooking
  `structlog` JSON output is one line in `src/app.py:lifespan`.
- GPU metrics are exposed via `/api/system/gpu` (it shells out to
  `nvidia-smi`).

## 6. Backups

`postgres_data` is the only stateful volume that matters. A one-liner:

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "backup-$(date +%F).sql.gz"
```

n8n state lives in `n8n_data` (sqlite). Snapshot the volume if you've
customised workflows.

## 7. Updating

```bash
git pull
docker compose --profile gpu pull        # pulls postgres / redis / n8n / ollama / vllm
docker compose --profile gpu up -d --build
```

The `init_db.sql` schema is idempotent (`CREATE TABLE IF NOT EXISTS`),
so re-runs are safe.

## 8. Rollback

The release CI pushes immutable tags `ghcr.io/saijayanth888/modelforge-api:vX.Y.Z`.
Pin those in a `docker-compose.override.yml` and roll back by changing
the tag and `docker compose up -d`.
