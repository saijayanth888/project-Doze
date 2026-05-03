"""Async Postgres pool + idempotent schema bootstrap.

The schema here is the *runtime* source of truth.
``scripts/postgres-init/01-modelforge.sql`` mirrors it for hosts that
bootstrap Postgres via the ``ankane/pgvector`` docker-entrypoint-initdb.d
folder.
"""

from __future__ import annotations

import logging

import asyncpg

from config.settings import settings

logger = logging.getLogger("modelforge.db")
_pool: asyncpg.Pool | None = None


# ── Connection initializer ───────────────────────────────────────────
async def _init_connection(conn: asyncpg.Connection) -> None:
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as exc:
        logger.debug("pgvector extension setup skipped: %s", exc)
    try:
        from pgvector.asyncpg import register_vector

        await register_vector(conn)
    except Exception as exc:
        logger.debug("pgvector codec registration skipped: %s", exc)


# ── Schema bootstrap ─────────────────────────────────────────────────
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS evolution_runs (
        run_id              TEXT PRIMARY KEY,
        base_model          TEXT NOT NULL,
        status              TEXT NOT NULL DEFAULT 'starting',
        current_generation  INT NOT NULL DEFAULT 0,
        current_step        TEXT,
        config              JSONB NOT NULL DEFAULT '{}'::jsonb,
        error               TEXT,
        started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at        TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generations (
        id                  SERIAL PRIMARY KEY,
        run_id              TEXT NOT NULL REFERENCES evolution_runs(run_id) ON DELETE CASCADE,
        generation          INT NOT NULL,
        promoted            BOOLEAN NOT NULL DEFAULT FALSE,
        is_champion         BOOLEAN NOT NULL DEFAULT FALSE,
        parent_scores       JSONB NOT NULL DEFAULT '{}'::jsonb,
        child_scores        JSONB NOT NULL DEFAULT '{}'::jsonb,
        decision_reason     TEXT,
        method              TEXT,
        training_data_size  INT NOT NULL DEFAULT 0,
        duration_seconds    DOUBLE PRECISION NOT NULL DEFAULT 0,
        data                JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (run_id, generation)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchmark_scores (
        id          SERIAL PRIMARY KEY,
        run_id      TEXT REFERENCES evolution_runs(run_id) ON DELETE CASCADE,
        generation  INT NOT NULL,
        benchmark   TEXT NOT NULL,
        score       DOUBLE PRECISION NOT NULL,
        promoted    BOOLEAN NOT NULL DEFAULT FALSE,
        scored_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON evolution_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_gen_run ON generations(run_id, generation DESC)",
    "CREATE INDEX IF NOT EXISTS idx_bench_run_gen ON benchmark_scores(run_id, generation)",
)


async def init_db() -> asyncpg.Pool:
    """Create the connection pool and ensure the schema exists."""
    global _pool

    # asyncpg expects the bare DSN, not the SQLAlchemy "+asyncpg" form.
    dsn = settings.database_url.replace("+asyncpg", "")
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        init=_init_connection,
    )

    async with _pool.acquire() as conn:
        for statement in _SCHEMA_STATEMENTS:
            await conn.execute(statement)
    logger.info("Database schema initialized")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool | None:
    return _pool
