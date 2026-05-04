"""Async Postgres pool + idempotent schema bootstrap.

The schema here is the *runtime* source of truth.
``scripts/postgres-init/01-modelforge.sql`` mirrors it for hosts that
bootstrap Postgres via the ``ankane/pgvector`` docker-entrypoint-initdb.d
folder.
"""

from __future__ import annotations

import json
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
        weak_categories     JSONB NOT NULL DEFAULT '[]'::jsonb,
        parent_scores       JSONB NOT NULL DEFAULT '{}'::jsonb,
        child_scores        JSONB NOT NULL DEFAULT '{}'::jsonb,
        decision_reason     TEXT,
        method              TEXT,
        training_data_size  INT NOT NULL DEFAULT 0,
        duration_seconds    DOUBLE PRECISION NOT NULL DEFAULT 0,
        data                JSONB NOT NULL DEFAULT '{}'::jsonb,
        archived            BOOLEAN NOT NULL DEFAULT FALSE,
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
    """
    CREATE TABLE IF NOT EXISTS model_embeddings (
        id          SERIAL PRIMARY KEY,
        run_id      TEXT REFERENCES evolution_runs(run_id) ON DELETE CASCADE,
        generation  INT NOT NULL,
        model_id    TEXT NOT NULL,
        prompt      TEXT NOT NULL,
        response    TEXT NOT NULL,
        embedding   vector(384),
        benchmark   TEXT,
        score       FLOAT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS training_samples (
        id              SERIAL PRIMARY KEY,
        generation      INT NOT NULL,
        source          TEXT NOT NULL,
        dataset_name    TEXT,
        category        TEXT,
        instruction     TEXT NOT NULL,
        response        TEXT NOT NULL,
        embedding       vector(384),
        quality_score   FLOAT,
        content_hash    TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evolution_presets (
        name        TEXT PRIMARY KEY,
        is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
        config      JSONB NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON evolution_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_gen_run ON generations(run_id, generation DESC)",
    "CREATE INDEX IF NOT EXISTS idx_bench_run_gen ON benchmark_scores(run_id, generation)",
    "CREATE INDEX IF NOT EXISTS idx_emb_hnsw ON model_embeddings USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)",
    "CREATE INDEX IF NOT EXISTS idx_emb_gen ON model_embeddings(generation)",
    "CREATE INDEX IF NOT EXISTS idx_train_hnsw ON training_samples USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)",
    "CREATE INDEX IF NOT EXISTS idx_train_gen ON training_samples(generation)",
    "CREATE INDEX IF NOT EXISTS idx_train_cat ON training_samples(category)",
    "CREATE INDEX IF NOT EXISTS idx_train_hash ON training_samples(content_hash) WHERE content_hash IS NOT NULL",
    "ALTER TABLE generations ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS content_hash TEXT",
)


_BUILTIN_PRESET_CONFIGS: list[tuple[str, bool, dict]] = [
    (
        "quick-test",
        True,
        {
            "base_model": "llama3.2:3b",
            "max_generations": 2,
            "lora_rank": 8,
            "lora_alpha": 16,
            "learning_rate": 2e-4,
            "batch_size": 2,
            "max_samples": 500,
            "benchmark_focus": ["mmlu"],
        },
    ),
    (
        "standard",
        True,
        {
            "base_model": "llama3.2:3b",
            "max_generations": 10,
            "lora_rank": 16,
            "lora_alpha": 32,
            "learning_rate": 2e-4,
            "batch_size": 2,
            "max_samples": 3000,
        },
    ),
    (
        "deep-evolution",
        True,
        {
            "base_model": "llama3.2:3b",
            "max_generations": 25,
            "lora_rank": 32,
            "lora_alpha": 64,
            "learning_rate": 1.5e-4,
            "batch_size": 2,
            "max_samples": 5000,
        },
    ),
    (
        "code-specialist",
        True,
        {
            "base_model": "llama3.2:3b",
            "max_generations": 15,
            "lora_rank": 16,
            "lora_alpha": 32,
            "learning_rate": 2e-4,
            "batch_size": 2,
            "max_samples": 3000,
            "benchmark_focus": ["humaneval", "gsm8k"],
        },
    ),
    (
        "reasoning-specialist",
        True,
        {
            "base_model": "llama3.2:3b",
            "max_generations": 15,
            "lora_rank": 16,
            "lora_alpha": 32,
            "learning_rate": 2e-4,
            "batch_size": 2,
            "max_samples": 3000,
            "benchmark_focus": ["arc_challenge", "hellaswag"],
        },
    ),
]


async def seed_builtin_presets(pool: asyncpg.Pool | None) -> None:
    """Idempotent insert of built-in evolution presets."""
    if pool is None:
        return
    async with pool.acquire() as conn:
        for name, is_builtin, cfg in _BUILTIN_PRESET_CONFIGS:
            await conn.execute(
                """
                INSERT INTO evolution_presets (name, is_builtin, config)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (name) DO NOTHING
                """,
                name,
                is_builtin,
                json.dumps(cfg),
            )
    logger.info("Built-in evolution presets ensured")


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
    await seed_builtin_presets(_pool)
    logger.info("Database schema initialized")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool | None:
    return _pool
