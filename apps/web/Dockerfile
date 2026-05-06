## Build context: repository root (see docker-compose.yml).
## ── Build stage ──────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY apps/web/frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit --no-fund

COPY apps/web/frontend/ ./

# Empty API base = same-origin /api via nginx (see infra/nginx.conf).
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
# Used by Settings defaults (see SettingsPage.jsx).
ARG VITE_OLLAMA_HOST=http://localhost:11434
ENV VITE_OLLAMA_HOST=$VITE_OLLAMA_HOST
ARG VITE_VLLM_HOST=http://localhost:8001
ENV VITE_VLLM_HOST=$VITE_VLLM_HOST
ARG VITE_N8N_HOST=http://localhost:5679
ENV VITE_N8N_HOST=$VITE_N8N_HOST
# Optional LAN/private deploy: default API key so dashboard loads without Settings (do not publish image publicly).
ARG VITE_MODELFORGE_API_KEY=
ENV VITE_MODELFORGE_API_KEY=$VITE_MODELFORGE_API_KEY
RUN npm run build

## ── Runtime stage ────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
