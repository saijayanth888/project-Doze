"""API-key authentication middleware.

Protects every ``/api/*`` and ``/ws/*`` path with a constant-time
comparison against ``settings.api_key`` (header ``X-API-Key`` or query
param ``api_key`` for WebSocket clients that can't send headers).

Allowlist (always public):
- ``/api/system/health``  — liveness/readiness probe
- ``/api/system/status``  — lightweight status used by reverse proxies
- ``/docs`` / ``/redoc``  — only mounted in non-production envs anyway
- ``/openapi.json``       — needed by /docs

Behaviour:
- ``ENVIRONMENT=production`` and no ``api_key`` set → ``settings`` raises
  during startup (see ``Settings.validate_for_runtime``).
- ``ENVIRONMENT=development`` and no ``api_key`` set → middleware logs
  a single warning and lets requests through (dev convenience).
"""

from __future__ import annotations

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Module reference (not the bound instance) so test reloads of
# config.settings are picked up at request time.
from config import settings as _settings_module

logger = logging.getLogger("modelforge.auth")

_ALLOWLIST: tuple[str, ...] = (
    "/api/system/health",
    "/api/system/status",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)

# WebSocket paths are mounted under /api in api_router but accept the key
# via either the header or a `?api_key=...` query param.
_WS_PATH_PREFIX = "/api/ws/"


def _is_allowlisted(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _ALLOWLIST)


def _eq_const(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class APIKeyMiddleware(BaseHTTPMiddleware):
    _warned_no_key: bool = False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not path.startswith("/api/") or _is_allowlisted(path):
            return await call_next(request)

        configured_key = _settings_module.settings.api_key

        if not configured_key:
            if not APIKeyMiddleware._warned_no_key:
                logger.warning(
                    "MODELFORGE_API_KEY is unset — leaving %s open (dev mode).",
                    path,
                )
                APIKeyMiddleware._warned_no_key = True
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if not provided and path.startswith(_WS_PATH_PREFIX):
            provided = request.query_params.get("api_key", "")

        if not provided or not _eq_const(provided, configured_key):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Missing or invalid X-API-Key",
                    "status": "error",
                    "code": 401,
                },
            )

        return await call_next(request)
