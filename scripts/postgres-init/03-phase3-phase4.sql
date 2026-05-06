-- Phase-3 / Phase-4 schema additions.
-- Idempotent so existing volumes keep working without re-init.
-- ─── PHASE 4: Specialist evolution tracks ────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_tracks (
    track_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    base_model TEXT NOT NULL,
    target_benchmarks JSONB NOT NULL DEFAULT '[]'::jsonb,
    champion_adapter_path TEXT,
    champion_run_id TEXT,
    champion_generation INT NOT NULL DEFAULT 0,
    champion_scores JSONB DEFAULT '{}'::jsonb,
    lora_rank INT NOT NULL DEFAULT 16,
    lora_alpha INT NOT NULL DEFAULT 32,
    learning_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0002,
    max_samples INT NOT NULL DEFAULT 2000,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tracks_enabled ON evolution_tracks (enabled);

CREATE TABLE IF NOT EXISTS track_generations (
    id SERIAL PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES evolution_tracks(track_id) ON DELETE CASCADE,
    generation INT NOT NULL,
    run_id TEXT,
    scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    promoted BOOLEAN NOT NULL DEFAULT FALSE,
    adapter_path TEXT,
    training_duration_sec DOUBLE PRECISION,
    eval_duration_sec DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_track_gens_track ON track_generations (track_id, generation);
CREATE INDEX IF NOT EXISTS idx_track_gens_run  ON track_generations (run_id);

-- ─── PHASE 3: Evolution-run schedule (the API tracks state; n8n triggers) ─

CREATE TABLE IF NOT EXISTS evolution_schedule (
    id INT PRIMARY KEY DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    cron TEXT NOT NULL DEFAULT '0 3 * * *',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_run_id TEXT,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (id = 1)
);

INSERT INTO evolution_schedule (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ─── PHASE 3: Soft-delete column for evolution_runs ──────────────────────

ALTER TABLE evolution_runs
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
