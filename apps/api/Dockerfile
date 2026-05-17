## Build context: repository root (see docker-compose.yml).
## ── Build stage ──────────────────────────────────────
FROM python:3.13-slim AS builder
WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY apps/api/requirements.txt .
# Resolver is uv with a 48h release-age cooldown — refuses versions published in the last 2 days.
RUN pip install --no-cache-dir "uv==0.11.11" \
    && UV_EXCLUDE_NEWER="$(date -u -d '2 days ago' +%Y-%m-%d)" \
       uv pip install --prefix=/install --no-cache -r requirements.txt

## ── Runtime stage ────────────────────────────────────
FROM python:3.13-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    MODELFORGE_LLAMA_CPP_CONVERT=/opt/llama.cpp/convert_lora_to_gguf.py

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git tini \
    && rm -rf /var/lib/apt/lists/*

# llama.cpp — shallow-clone at a pinned commit so the
# publish_adapter_to_ollama action has a working LoRA→GGUF converter
# without depending on a host-side llama.cpp install. We need the full
# conversion/ package (convert_lora_to_gguf.py imports
# `from conversion import LazyTorchTensor, ModelBase, get_model_class`)
# plus convert_hf_to_gguf.py and gguf-py — fetching individual files
# missed transitive deps and broke at first invocation
# (audit 2026-05-17 attempt 1).
#
# Bump LLAMA_CPP_COMMIT if upstream changes the converter API. Shallow
# clone keeps the layer size minimal (~30 MB of Python).
ARG LLAMA_CPP_COMMIT=87589042cac2c390cec8d68fb2fad64e0a2a252a
RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp.git \
    && cd /opt/llama.cpp.git \
    && git fetch --depth 1 origin ${LLAMA_CPP_COMMIT} \
    && git checkout ${LLAMA_CPP_COMMIT} \
    && mkdir -p /opt/llama.cpp \
    && cp convert_lora_to_gguf.py convert_hf_to_gguf.py /opt/llama.cpp/ \
    && cp -r conversion /opt/llama.cpp/ \
    && cp -r gguf-py /opt/llama.cpp/ \
    && chmod +x /opt/llama.cpp/convert_lora_to_gguf.py \
    && rm -rf /opt/llama.cpp.git
ENV PYTHONPATH=/app/src:/opt/llama.cpp:/opt/llama.cpp/gguf-py

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app /opt/llama.cpp

COPY --from=builder /install /usr/local
COPY --chown=app:app apps/api/src/ ./src/

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/system/status || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
