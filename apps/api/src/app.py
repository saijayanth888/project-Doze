"""FastAPI application factory and lifespan.

This module performs three production-critical jobs:

1. Validates settings at startup (``settings.validate_for_runtime``) so
   misconfigured production deployments fail fast instead of silently.
2. Configures CORS safely: when ``CORS_ORIGINS`` contains ``*``, the
   ``allow_credentials`` flag is forced to ``False`` because the CORS
   spec rejects the wildcard-with-credentials combination.
3. Wires up the ``APIKeyMiddleware`` (X-API-Key auth with allowlisted
   public paths) and ``SecurityHeadersMiddleware``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router
from config.database import close_db, init_db
from config.redis_pool import close_redis
from config.settings import settings
from middleware.auth import APIKeyMiddleware
from middleware.errors import register_exception_handlers
from middleware.logging import LoggingMiddleware
from middleware.security import SecurityHeadersMiddleware

logger = logging.getLogger("modelforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    settings.validate_for_runtime()
    logger.info("Starting ModelForge API — env=%s", settings.environment)

    try:
        app.state.db_pool = await init_db()
        logger.info("PostgreSQL + pgvector connected")
    except Exception as exc:
        logger.warning("DB init failed (mock mode): %s", exc)
        app.state.db_pool = None

    # Phase-3/4 idempotent migrations + default track seeding. Both are best-
    # effort — failures are logged but never block the API from booting.
    if app.state.db_pool is not None:
        try:
            from services.lineage_db import LineageDB
            db = LineageDB(app.state.db_pool)
            await db.apply_phase34_migrations()
            from services.track_seed import seed_default_tracks
            await seed_default_tracks(db)
        except Exception as exc:
            logger.warning("phase3/4 migration/seed skipped: %s", exc)

    yield

    await close_redis()
    await close_db()
    logger.info("ModelForge API shutdown")


def _build_cors_kwargs() -> dict:
    """Return safe CORS kwargs.

    Wildcard origins force ``allow_credentials=False`` to satisfy the
    CORS spec; we also strip ``*`` from the explicit origin list since
    the wildcard is handled separately by the browser.
    """
    origins = settings.cors_origin_list
    has_wildcard = settings.cors_has_wildcard
    explicit = [o for o in origins if o != "*"]

    if has_wildcard:
        return {
            "allow_origins": ["*"],
            "allow_credentials": False,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }

    return {
        "allow_origins": explicit,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*", "X-API-Key"],
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="ModelForge",
        description="Self-Evolving LLM Platform — Autonomous Model Evolution Engine",
        version="0.1.0",
        # Some clients POST to paths without the trailing slash and previously got 307s.
        # Disable redirects to ensure the request reaches the intended route.
        redirect_slashes=False,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(CORSMiddleware, **_build_cors_kwargs())
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(APIKeyMiddleware)
    app.add_middleware(LoggingMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api")

    return app
