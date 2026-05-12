-- Production-hardening indices.
-- Idempotent — safe to re-run on existing volumes.
--
-- Query patterns these support (see apps/api/src/services/lineage_db.py):
--   * get_dashboard_run(): WHERE status NOT IN (...) ORDER BY started_at DESC
--     → needs an index on started_at to avoid a full-table sort.
--   * list_runs() / get_run_history(): ORDER BY r.started_at DESC NULLS LAST
--     → same.
--   * archive_run(run_id): WHERE archived_at IS NULL — selective filter.
--   * benchmark_scores: per-run-per-benchmark lookups (drill-down chart) —
--     idx_bench_run_gen handles (run_id, generation) but the chart also
--     queries by (run_id, benchmark), which had no covering index.
--   * track_generations: lookups by (track_id, promoted) for "current
--     champion of this track" — already covered by (track_id, generation)
--     scans but a partial index on the small promoted=true set is cheaper.
--
-- These tables can grow into the 10k–1M row range over the lifetime of a
-- deployment (each evolution run = ~10 generations = up to ~50 benchmark
-- rows, plus per-generation embeddings). The indices below are picked so
-- the cost is bounded but the dashboard reads stay O(log n).

-- evolution_runs: ORDER BY started_at DESC is the hot path.
CREATE INDEX IF NOT EXISTS idx_runs_started_at
    ON evolution_runs (started_at DESC);

-- evolution_runs: archived-list filter is a partial index on the small
-- non-archived subset (most runs stay un-archived).
CREATE INDEX IF NOT EXISTS idx_runs_active
    ON evolution_runs (started_at DESC) WHERE archived_at IS NULL;

-- benchmark_scores: per-run-per-benchmark drill-downs.
CREATE INDEX IF NOT EXISTS idx_bench_run_bench
    ON benchmark_scores (run_id, benchmark);

-- track_generations: "what's promoted for this track" is a small set.
CREATE INDEX IF NOT EXISTS idx_track_gens_promoted
    ON track_generations (track_id, generation DESC) WHERE promoted;

-- generations: champion lookups.
CREATE INDEX IF NOT EXISTS idx_gen_champion
    ON generations (run_id) WHERE is_champion;

-- generations: promoted lookups for drift detection.
CREATE INDEX IF NOT EXISTS idx_gen_promoted
    ON generations (run_id, generation DESC) WHERE promoted;
