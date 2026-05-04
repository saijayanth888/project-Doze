"""Singleton async Redis client for WebSocket + pub/sub."""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis

from config.settings import settings

logger = logging.getLogger("modelforge.redis")

_client: Any = None


async def get_redis() -> Any:
    """Return shared ``redis.asyncio.Redis`` or None if connection fails."""
    global _client
    if _client is not None:
        return _client
    try:
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await _client.ping()
        logger.info("Redis connected for pub/sub")
        return _client
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — training WS will not stream", exc)
        _client = None
        return None


async def close_redis() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as exc:
            logger.debug("Redis close: %s", exc)
        _client = None
