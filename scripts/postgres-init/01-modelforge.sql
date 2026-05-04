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

-- Model output embeddings (for drift detection between generations)
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
);

CREATE INDEX IF NOT EXISTS idx_emb_hnsw ON model_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX IF NOT EXISTS idx_emb_gen ON model_embeddings(generation);

-- Training samples with embeddings (for deduplication across generations)
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
);

CREATE INDEX IF NOT EXISTS idx_train_hnsw ON training_samples
    USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX IF NOT EXISTS idx_train_gen ON training_samples(generation);
CREATE INDEX IF NOT EXISTS idx_train_cat ON training_samples(category);
CREATE INDEX IF NOT EXISTS idx_train_hash ON training_samples(content_hash) WHERE content_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS evolution_presets (
    name        TEXT PRIMARY KEY,
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    config      JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
