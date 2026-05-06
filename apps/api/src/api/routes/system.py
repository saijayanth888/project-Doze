"""System health, GPU status, and environment info routes."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys

from fastapi import APIRouter, Depends, HTTPException
from starlette import status as http_status

from api.deps import get_db, get_ollama
from api.schemas.system import EnvironmentInfo, GPUStatus, HealthCheck, N8nAlertIn
from config.settings import settings
from services.lineage_db import LineageDB
from services.ollama_client import OllamaClient
from utils.gpu import get_gpu_status

logger = logging.getLogger("modelforge.routes.system")

router = APIRouter()


async def _check_postgres(db: LineageDB) -> str:
    return "ok" if await db.ping() else "degraded"


async def _check_redis() -> str:
    """Ping Redis using the configured URL (settings.redis_url)."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            await client.ping()
            return "ok"
        finally:
            await client.aclose()
    except Exception as exc:
        logger.debug("Redis health check failed (non-critical): %s", exc)
        return "degraded"


@router.get("/health", response_model=HealthCheck)
async def health_check(
    db: LineageDB = Depends(get_db),
) -> HealthCheck:
    """Liveness + readiness check across DB, Redis, and Ollama."""
    ollama = await get_ollama()

    postgres_status, redis_status, ollama_status = await asyncio.gather(
        _check_postgres(db),
        _check_redis(),
        ollama.health_check(),
    )

    overall = "ok" if postgres_status == "ok" else "degraded"

    return HealthCheck(
        status=overall,
        environment=settings.environment,
        postgres=postgres_status,
        redis=redis_status,
        ollama=ollama_status,
    )


@router.get("/status")
async def liveness() -> dict:
    """Lightweight status endpoint for reverse proxies and the SPA."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": "0.1.0",
    }


@router.get("/gpu", response_model=GPUStatus)
async def gpu_status(ollama: OllamaClient = Depends(get_ollama)) -> GPUStatus:
    payload: dict = dict(get_gpu_status())
    payload["ollama_inference_ok"] = False
    try:
        payload["ollama_inference_ok"] = await ollama.health_check() == "ok"
    except Exception as exc:
        logger.debug("Ollama health for GPU payload failed: %s", exc)
    return GPUStatus(**payload)


@router.get("/ollama-models")
async def ollama_model_tags(ollama: OllamaClient = Depends(get_ollama)) -> dict[str, list[str]]:
    """Tags currently available in Ollama (`/api/tags`) for evolution base-model pickers."""
    try:
        rows = await ollama.list_models()
    except Exception as exc:
        logger.warning("ollama list_models failed: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama unreachable — start the `ollama` service and gpu profile if needed.",
        ) from exc

    names: list[str] = []
    for m in rows:
        n = m.get("name") or m.get("model")
        if n:
            names.append(str(n))
    return {"models": sorted(set(names))}


@router.post("/alerts", status_code=http_status.HTTP_202_ACCEPTED)
async def ingest_n8n_alert(payload: N8nAlertIn) -> dict:
    """Accept health / automation alerts POSTed from n8n workflows.

    Persists nothing by default — logs at WARNING for observability hooks.
    Extend this handler to write to Postgres or forward to PagerDuty.
    """
    logger.warning(
        "n8n alert: type=%s severity=%s services=%s api=%s pg=%s redis=%s",
        payload.alert_type,
        payload.severity,
        payload.failed_services,
        payload.api_status,
        payload.postgres_status,
        payload.redis_status,
    )
    return {"status": "accepted", "alert_type": payload.alert_type}


@router.get("/storage")
async def storage_usage() -> dict:
    """Walk the data root and report usage per top-level category.

    Buckets:
      - adapters         (data/adapters/<run>/gen-N/)
      - curated          (data/curated/gen-N/)
      - ept              (data/ept/<run>/)
      - hf_cache         (data/.cache/huggingface/)
      - registry         (data/registry.json + small leaf files)

    Returns per-bucket size + file count, plus a `total_bytes` and
    `total_human` for the whole data root. Walks each bucket in a thread
    so we don't block the event loop on large directories.
    """
    from pathlib import Path

    def _scan(path: Path) -> tuple[int, int]:
        total_bytes = 0
        total_files = 0
        if not path.exists():
            return 0, 0
        if path.is_file():
            try:
                return path.stat().st_size, 1
            except OSError:
                return 0, 0
        for f in path.rglob("*"):
            try:
                if f.is_file():
                    total_bytes += f.stat().st_size
                    total_files += 1
            except OSError:
                pass
        return total_bytes, total_files

    def _human(b: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"

    data_root = Path(settings.resolve_data_root())
    buckets = {
        "adapters": data_root / "adapters",
        "curated":  data_root / "curated",
        "ept":      data_root / "ept",
        "hf_cache": data_root / ".cache",
        "registry": data_root / "registry.json",
    }

    loop = asyncio.get_running_loop()
    results: dict[str, dict] = {}
    total = 0
    files = 0
    for name, p in buckets.items():
        size, n = await loop.run_in_executor(None, _scan, p)
        results[name] = {
            "path": str(p),
            "exists": p.exists(),
            "bytes": int(size),
            "human": _human(size),
            "files": int(n),
        }
        total += size
        files += n

    # Free disk inspection — best-effort.
    try:
        st = await loop.run_in_executor(None, lambda: __import__("shutil").disk_usage(str(data_root)))
        free_bytes = int(st.free)
        total_bytes_disk = int(st.total)
    except Exception:
        free_bytes = None
        total_bytes_disk = None

    return {
        "data_root": str(data_root),
        "buckets": results,
        "total_bytes": int(total),
        "total_human": _human(total),
        "total_files": int(files),
        "free_bytes": free_bytes,
        "total_disk_bytes": total_bytes_disk,
        "free_human": _human(free_bytes) if free_bytes is not None else None,
        "total_disk_human": _human(total_bytes_disk) if total_bytes_disk is not None else None,
    }


@router.get("/env", response_model=EnvironmentInfo)
async def environment_info() -> EnvironmentInfo:
    gpu_data = get_gpu_status()

    db_url = settings.database_url
    try:
        db_host = db_url.split("@")[-1].split("/")[0]
    except Exception:
        db_host = "unknown"

    return EnvironmentInfo(
        environment=settings.environment,
        python_version=sys.version,
        platform=platform.platform(),
        gpu_available=gpu_data.get("gpu_available", False),
        ollama_host=settings.ollama_host,
        db_host=db_host,
        features={
            "lora_training": True,
            "benchmark_eval": True,
            "websocket_stream": True,
            "vllm": bool(settings.vllm_api_key),
        },
    )
