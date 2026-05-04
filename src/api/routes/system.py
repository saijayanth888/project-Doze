"""System health, GPU status, and environment info routes."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys

from fastapi import APIRouter, Depends, status

from api.deps import get_db, get_ollama
from api.schemas.system import EnvironmentInfo, GPUStatus, HealthCheck, N8nAlertIn
from config.settings import settings
from services.lineage_db import LineageDB
from utils.gpu import get_gpu_status

logger = logging.getLogger("modelforge.routes.system")

router = APIRouter()


async def _check_postgres(db: LineageDB) -> str:
    return "ok" if await db.ping() else "degraded"


async def _check_redis() -> str:
    """Ping Redis using the configured URL (settings.redis_url)."""
    try:
        import redis.asyncio as aioredis  # type: ignore

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
async def status() -> dict:
    """Lightweight status endpoint for reverse proxies and the SPA."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": "0.1.0",
    }


@router.get("/gpu", response_model=GPUStatus)
async def gpu_status() -> GPUStatus:
    return GPUStatus(**get_gpu_status())


@router.post("/alerts", status_code=status.HTTP_202_ACCEPTED)
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
