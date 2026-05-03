-- ModelForge schema bootstrap (modelforge database).
-- Mirrors apps/api/src/config/database.py:_SCHEMA_STATEMENTS — keep in sync.

CREATE EXTENSION IF NOT EXISTS vector;

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
);

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
);

CREATE TABLE IF NOT EXISTS benchmark_scores (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT REFERENCES evolution_runs(run_id) ON DELETE CASCADE,
    generation  INT NOT NULL,
    benchmark   TEXT NOT NULL,
    score       DOUBLE PRECISION NOT NULL,
    promoted    BOOLEAN NOT NULL DEFAULT FALSE,
    scored_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON evolution_runs(status);
CREATE INDEX IF NOT EXISTS idx_gen_run ON generations(run_id, generation DESC);
CREATE INDEX IF NOT EXISTS idx_bench_run_gen ON benchmark_scores(run_id, generation);
