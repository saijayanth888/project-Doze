"""Postgres-backed read/write helpers for evolution lineage data.

Every method is safe to call when the pool is ``None`` (DB unavailable):
reads return empty results, writes are silently no-op'd. This keeps the
API responsive in dev / Mac mode where Postgres may not be running.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("modelforge.lineage_db")


class LineageDB:
    def __init__(self, pool: Any = None) -> None:
        self._pool = pool

    @property
    def has_pool(self) -> bool:
        return self._pool is not None

    async def ping(self) -> bool:
        """Return True iff the pool is reachable (used by /api/system/health)."""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("LineageDB.ping failed: %s", exc)
            return False

    # ── Generations ────────────────────────────────────────────────
    async def get_all_generations(
        self,
        run_id: str | None = None,
        *,
        include_archived: bool = True,
    ) -> list[dict]:
        if self._pool is None:
            return []
        extra = "" if include_archived else " AND (archived IS NULL OR archived = FALSE)"
        async with self._pool.acquire() as conn:
            if run_id is not None:
                rows = await conn.fetch(
                    f"SELECT * FROM generations WHERE run_id = $1{extra} ORDER BY generation ASC",
                    run_id,
                )
            else:
                rows = await conn.fetch(
                    f"SELECT * FROM generations WHERE TRUE{extra} ORDER BY generation ASC"
                )
            return [dict(r) for r in rows]

    async def get_generation(self, run_id: str, generation: int) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM generations WHERE run_id = $1 AND generation = $2",
                run_id,
                generation,
            )
            return dict(row) if row else None

    async def save_generation(self, run_id: str, gen_data: dict) -> None:
        """UPSERT a generation row keyed by (run_id, generation)."""
        if self._pool is None:
            return
        generation = int(gen_data.get("generation", 0))
        promoted = bool(gen_data.get("promoted", False))
        is_champion = bool(gen_data.get("is_champion", False))
        weak_categories = gen_data.get("weak_categories", []) or []
        parent_scores = gen_data.get("parent_scores", {}) or {}
        child_scores = gen_data.get("child_scores", gen_data.get("scores", {})) or {}
        decision_reason = gen_data.get("decision_reason")
        method = gen_data.get("method")
        training_size = int(gen_data.get("training_data_size", 0))
        duration = float(gen_data.get("duration_seconds", 0.0))
        archived = bool(gen_data.get("archived", False))

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO generations (
                    run_id, generation, promoted, is_champion,
                    weak_categories, parent_scores, child_scores, decision_reason, method,
                    training_data_size, duration_seconds, data, archived
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12::jsonb, $13)
                ON CONFLICT (run_id, generation) DO UPDATE SET
                    promoted          = EXCLUDED.promoted,
                    is_champion       = EXCLUDED.is_champion,
                    weak_categories   = EXCLUDED.weak_categories,
                    parent_scores     = EXCLUDED.parent_scores,
                    child_scores      = EXCLUDED.child_scores,
                    decision_reason   = EXCLUDED.decision_reason,
                    method            = EXCLUDED.method,
                    training_data_size= EXCLUDED.training_data_size,
                    duration_seconds  = EXCLUDED.duration_seconds,
                    data              = EXCLUDED.data,
                    archived          = EXCLUDED.archived
                """,
                run_id,
                generation,
                promoted,
                is_champion,
                json.dumps(weak_categories),
                json.dumps(parent_scores),
                json.dumps(child_scores),
                decision_reason,
                method,
                training_size,
                duration,
                json.dumps(gen_data, default=str),
                archived,
            )

    # ── Evolution runs ─────────────────────────────────────────────
    async def get_run(self, run_id: str) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM evolution_runs WHERE run_id = $1", run_id)
            return dict(row) if row else None

    async def has_evolution_runs(self) -> bool:
        """True when at least one row exists in ``evolution_runs``.

        Used to avoid showing orphan ``benchmark_scores`` / ``generations`` rows
        when the dashboard evolution poll reports no run (empty ``evolution_runs``).
        """
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*)::bigint FROM evolution_runs")
            return int(n or 0) > 0

    async def get_dashboard_run(self) -> dict | None:
        """Prefer an in-flight run; otherwise the most recent run (any status)."""
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM evolution_runs
                WHERE status NOT IN ('completed', 'failed', 'stopped')
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            if row:
                return dict(row)
            row = await conn.fetchrow(
                "SELECT * FROM evolution_runs ORDER BY started_at DESC LIMIT 1"
            )
            return dict(row) if row else None

    async def save_run(self, run_id: str, status: str, config: dict) -> None:
        if self._pool is None:
            return
        base_model = str(config.get("base_model", "")) or "unknown"
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evolution_runs (run_id, base_model, status, config)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET
                    base_model = EXCLUDED.base_model,
                    status     = EXCLUDED.status,
                    config     = EXCLUDED.config
                """,
                run_id,
                base_model,
                status,
                json.dumps(config),
            )

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        generation: int = 0,
        current_step: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE evolution_runs
                SET status              = $2,
                    current_generation  = $3,
                    current_step        = $4,
                    error               = COALESCE($5, error),
                    completed_at        = CASE
                        WHEN $2::text IN ('completed', 'failed', 'stopped')
                             AND completed_at IS NULL THEN NOW()
                        ELSE completed_at
                    END
                WHERE run_id = $1
                """,
                run_id,
                status,
                generation,
                current_step,
                error,
            )

    async def complete_run(self, run_id: str) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE evolution_runs
                SET status = 'completed', completed_at = NOW()
                WHERE run_id = $1
                """,
                run_id,
            )

    # ── Benchmark scores ───────────────────────────────────────────
    async def get_score_trends(self) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM benchmark_scores ORDER BY generation ASC")
            return [dict(r) for r in rows]

    async def save_score(
        self,
        run_id: str,
        generation: int,
        benchmark: str,
        score: float,
        promoted: bool,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO benchmark_scores (run_id, generation, benchmark, score, promoted)
                VALUES ($1, $2, $3, $4, $5)
                """,
                run_id,
                generation,
                benchmark,
                score,
                promoted,
            )

    # ── Embeddings / pgvector ───────────────────────────────────────
    async def store_embedding(
        self,
        run_id: str,
        generation: int,
        model_id: str,
        prompt: str,
        response: str,
        embedding: list[float],
        benchmark: str | None = None,
        score: float | None = None,
    ) -> None:
        """Store a model output with its embedding for drift detection."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO model_embeddings
                (run_id, generation, model_id, prompt, response, embedding, benchmark, score)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8)
                """,
                run_id,
                int(generation),
                model_id,
                prompt,
                response,
                str(embedding),
                benchmark,
                score,
            )

    async def find_similar_training(
        self, embedding: list[float], threshold: float = 0.92, limit: int = 10
    ) -> list[dict]:
        """Find training samples similar to a given embedding (deduplication)."""
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, instruction, category, generation,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM training_samples
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> $1::vector) > $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                str(embedding),
                float(threshold),
                int(limit),
            )
            return [dict(r) for r in rows]

    async def is_duplicate(self, embedding: list[float], threshold: float = 0.95) -> bool:
        """Check if a training sample is a near-duplicate."""
        results = await self.find_similar_training(embedding, threshold, limit=1)
        return len(results) > 0

    async def detect_drift(self, gen_a: int, gen_b: int, sample_size: int = 50) -> dict:
        """Compare model output distributions between two generations."""
        if self._pool is None:
            return {"drift_score": None, "message": "DB unavailable"}
        async with self._pool.acquire() as conn:
            rows_a = await conn.fetch(
                "SELECT embedding::text FROM model_embeddings WHERE generation=$1 LIMIT $2",
                int(gen_a),
                int(sample_size),
            )
            rows_b = await conn.fetch(
                "SELECT embedding::text FROM model_embeddings WHERE generation=$1 LIMIT $2",
                int(gen_b),
                int(sample_size),
            )
            if not rows_a or not rows_b:
                return {"drift_score": None, "message": "Insufficient data"}

            import json
            import math

            def parse_vec(row: Any) -> list[float]:
                # embedding::text is either "[...]" (codec) or "(...)" (pg)
                raw = row["embedding"]
                if isinstance(raw, str) and raw.startswith("(") and raw.endswith(")"):
                    raw = "[" + raw[1:-1] + "]"
                return json.loads(raw)

            vecs_a = [parse_vec(r) for r in rows_a]
            vecs_b = [parse_vec(r) for r in rows_b]

            if not vecs_a or not vecs_b:
                return {"drift_score": None, "message": "Insufficient data"}

            dim = len(vecs_a[0])
            centroid_a = [sum(v[i] for v in vecs_a) / len(vecs_a) for i in range(dim)]
            centroid_b = [sum(v[i] for v in vecs_b) / len(vecs_b) for i in range(dim)]
            drift = math.sqrt(sum((a - b) ** 2 for a, b in zip(centroid_a, centroid_b, strict=False)))
            return {
                "generation_a": int(gen_a),
                "generation_b": int(gen_b),
                "drift_score": round(float(drift), 4),
                "interpretation": "minimal"
                if drift < 0.1
                else "moderate"
                if drift < 0.3
                else "significant",
            }

    # ── Generations: champion / archive ─────────────────────────────
    async def set_generation_archived(self, run_id: str, generation: int, archived: bool = True) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generations SET archived = $3
                WHERE run_id = $1 AND generation = $2
                """,
                run_id,
                int(generation),
                archived,
            )

    async def clear_all_champions(self) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE generations SET is_champion = FALSE")

    async def set_champion_generation(self, run_id: str, generation: int) -> None:
        """Mark exactly one row as champion (clears other champion flags)."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE generations SET is_champion = FALSE")
            await conn.execute(
                """
                UPDATE generations SET is_champion = TRUE
                WHERE run_id = $1 AND generation = $2
                """,
                run_id,
                int(generation),
            )

    # ── Evolution presets ───────────────────────────────────────────
    async def list_evolution_presets(self) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM evolution_presets ORDER BY name ASC")
            return [dict(r) for r in rows]

    async def get_evolution_preset(self, name: str) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM evolution_presets WHERE name = $1",
                name,
            )
            return dict(row) if row else None

    async def upsert_evolution_preset(self, name: str, config: dict, *, is_builtin: bool = False) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evolution_presets (name, is_builtin, config)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (name) DO UPDATE SET
                    config = EXCLUDED.config,
                    is_builtin = EXCLUDED.is_builtin
                """,
                name,
                is_builtin,
                json.dumps(config),
            )

    async def delete_evolution_preset(self, name: str) -> bool:
        """Return True if a row was deleted."""
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM evolution_presets WHERE name = $1 AND is_builtin = FALSE",
                name,
            )
            # asyncpg returns "DELETE N"
            try:
                return int(res.split()[-1]) > 0
            except (ValueError, IndexError):
                return False

    # ── Training sample hashes (upload dedup / overlap) ────────────
    async def find_existing_content_hashes(self, hashes: list[str]) -> set[str]:
        if self._pool is None or not hashes:
            return set()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT content_hash FROM training_samples WHERE content_hash = ANY($1::text[])",
                hashes,
            )
            return {str(r["content_hash"]) for r in rows if r.get("content_hash")}

    async def insert_training_sample_row(
        self,
        *,
        generation: int,
        source: str,
        dataset_name: str | None,
        category: str | None,
        instruction: str,
        response: str,
        content_hash: str | None,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO training_samples
                    (generation, source, dataset_name, category, instruction, response, content_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                int(generation),
                source,
                dataset_name,
                category,
                instruction,
                response,
                content_hash,
            )

    async def count_hash_overlap_excluding_dataset(self, hashes: list[str], exclude_dataset: str) -> int:
        if self._pool is None or not hashes:
            return 0
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM training_samples
                WHERE content_hash = ANY($1::text[])
                  AND (dataset_name IS DISTINCT FROM $2)
                """,
                hashes,
                exclude_dataset,
            )
            return int(n or 0)

    # ── Phase-3/4 idempotent migrations ─────────────────────────────
    async def apply_phase34_migrations(self) -> None:
        """Idempotent CREATE statements for the new tables introduced by
        Phase 3 (run history archived_at, schedule) and Phase 4 (tracks).

        Safe to call on every API boot. Avoids needing to wipe the postgres
        volume on existing installs.
        """
        if self._pool is None:
            return
        ddl = [
            "ALTER TABLE evolution_runs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
            """
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
            )
            """,
            """
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
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_track_gens_track ON track_generations (track_id, generation)",
            """
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
            )
            """,
            "INSERT INTO evolution_schedule (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
        ]
        async with self._pool.acquire() as conn:
            for stmt in ddl:
                try:
                    await conn.execute(stmt)
                except Exception as exc:
                    logger.warning("apply_phase34_migrations stmt failed: %s | %s", exc, stmt[:80])

    # ── Phase-3: Run history ────────────────────────────────────────
    async def list_runs(
        self,
        *,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        if self._pool is None:
            return []
        where = "" if include_archived else "WHERE archived_at IS NULL"
        sql = f"""
            SELECT
                r.run_id,
                r.status,
                r.base_model,
                r.config,
                r.current_generation AS generations_completed,
                r.current_step,
                r.error,
                r.started_at,
                r.completed_at,
                r.archived_at,
                COALESCE(g.gen_count, 0)        AS gens_persisted,
                g.last_promoted_avg              AS final_champion_score,
                g.last_promoted_scores           AS final_scores
            FROM evolution_runs r
            LEFT JOIN (
                SELECT
                    run_id,
                    COUNT(*) AS gen_count,
                    (SELECT child_scores FROM generations g2
                       WHERE g2.run_id = generations.run_id AND g2.promoted
                       ORDER BY g2.generation DESC LIMIT 1) AS last_promoted_scores,
                    (SELECT (CASE WHEN jsonb_typeof(child_scores) = 'object'
                                  AND (SELECT count(*) FROM jsonb_object_keys(child_scores)) > 0
                                  THEN (
                                      SELECT avg((value)::text::double precision)
                                      FROM jsonb_each(child_scores)
                                  )
                                  ELSE NULL END)
                       FROM generations g3
                       WHERE g3.run_id = generations.run_id AND g3.promoted
                       ORDER BY g3.generation DESC LIMIT 1) AS last_promoted_avg
                FROM generations
                GROUP BY run_id
            ) g ON g.run_id = r.run_id
            {where}
            ORDER BY r.started_at DESC NULLS LAST
            LIMIT $1
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, int(limit))
        return [dict(r) for r in rows]

    async def archive_run(self, run_id: str) -> bool:
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            r = await conn.execute(
                "UPDATE evolution_runs SET archived_at = NOW() WHERE run_id = $1 AND archived_at IS NULL",
                run_id,
            )
            # asyncpg returns "UPDATE <count>" string; treat any UPDATE as success.
            return r.startswith("UPDATE") and not r.endswith(" 0")

    # ── Phase-3: Schedule ───────────────────────────────────────────
    async def get_schedule(self) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM evolution_schedule WHERE id = 1")
        return dict(row) if row else None

    async def update_schedule(
        self,
        *,
        enabled: bool | None = None,
        cron: str | None = None,
        config: dict | None = None,
        last_run_id: str | None = None,
        next_run_at: Any | None = None,
    ) -> dict | None:
        if self._pool is None:
            return None
        sets = []
        vals: list[Any] = []
        if enabled is not None:
            sets.append(f"enabled = ${len(vals) + 1}")
            vals.append(bool(enabled))
        if cron is not None:
            sets.append(f"cron = ${len(vals) + 1}")
            vals.append(str(cron))
        if config is not None:
            sets.append(f"config = ${len(vals) + 1}::jsonb")
            vals.append(json.dumps(config))
        if last_run_id is not None:
            sets.append(f"last_run_id = ${len(vals) + 1}")
            vals.append(str(last_run_id))
            sets.append("last_run_at = NOW()")
        if next_run_at is not None:
            sets.append(f"next_run_at = ${len(vals) + 1}")
            vals.append(next_run_at)
        if not sets:
            return await self.get_schedule()
        sets.append("updated_at = NOW()")
        sql = f"UPDATE evolution_schedule SET {', '.join(sets)} WHERE id = 1 RETURNING *"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *vals)
        return dict(row) if row else None

    # ── Phase-4: Tracks ─────────────────────────────────────────────
    async def list_tracks(self) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM evolution_tracks ORDER BY created_at ASC")
        return [_normalize_track_row(dict(r)) for r in rows]

    async def get_track(self, track_id: str) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM evolution_tracks WHERE track_id = $1", track_id)
        return _normalize_track_row(dict(row)) if row else None

    async def upsert_track(self, payload: dict) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO evolution_tracks (
                    track_id, name, description, base_model, target_benchmarks,
                    lora_rank, lora_alpha, learning_rate, max_samples, enabled
                )
                VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10)
                ON CONFLICT (track_id) DO UPDATE SET
                    name              = EXCLUDED.name,
                    description       = EXCLUDED.description,
                    base_model        = EXCLUDED.base_model,
                    target_benchmarks = EXCLUDED.target_benchmarks,
                    lora_rank         = EXCLUDED.lora_rank,
                    lora_alpha        = EXCLUDED.lora_alpha,
                    learning_rate     = EXCLUDED.learning_rate,
                    max_samples       = EXCLUDED.max_samples,
                    enabled           = EXCLUDED.enabled,
                    updated_at        = NOW()
                RETURNING *
                """,
                str(payload["track_id"]),
                str(payload.get("name") or payload["track_id"]),
                payload.get("description"),
                str(payload.get("base_model") or "llama3.2:3b"),
                json.dumps(payload.get("target_benchmarks") or []),
                int(payload.get("lora_rank") or 16),
                int(payload.get("lora_alpha") or 32),
                float(payload.get("learning_rate") or 2e-4),
                int(payload.get("max_samples") or 2000),
                bool(payload.get("enabled", True)),
            )
        return _normalize_track_row(dict(row)) if row else None

    async def delete_track(self, track_id: str) -> bool:
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            r = await conn.execute("DELETE FROM evolution_tracks WHERE track_id = $1", track_id)
        return r.startswith("DELETE") and not r.endswith(" 0")

    async def update_track_champion(
        self,
        track_id: str,
        *,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        scores: dict,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE evolution_tracks SET
                    champion_run_id = $2,
                    champion_generation = $3,
                    champion_adapter_path = $4,
                    champion_scores = $5::jsonb,
                    updated_at = NOW()
                WHERE track_id = $1
                """,
                track_id,
                run_id,
                int(generation),
                adapter_path,
                json.dumps(scores or {}),
            )

    async def list_track_generations(self, track_id: str, *, limit: int = 200) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM track_generations
                WHERE track_id = $1
                ORDER BY generation ASC
                LIMIT $2
                """,
                track_id,
                int(limit),
            )
        return [_normalize_track_gen_row(dict(r)) for r in rows]

    async def insert_track_generation(self, payload: dict) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO track_generations
                    (track_id, generation, run_id, scores, promoted, adapter_path,
                     training_duration_sec, eval_duration_sec)
                VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8)
                """,
                str(payload["track_id"]),
                int(payload.get("generation", 0)),
                payload.get("run_id"),
                json.dumps(payload.get("scores") or {}),
                bool(payload.get("promoted", False)),
                payload.get("adapter_path"),
                payload.get("training_duration_sec"),
                payload.get("eval_duration_sec"),
            )


def _coerce_jsonb(val: Any) -> Any:
    """asyncpg returns JSONB as a python value when the codec is registered, or
    as a string otherwise. Always return the python form."""
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def _normalize_track_row(row: dict) -> dict:
    out = dict(row)
    out["target_benchmarks"] = _coerce_jsonb(out.get("target_benchmarks")) or []
    out["champion_scores"] = _coerce_jsonb(out.get("champion_scores")) or {}
    return out


def _normalize_track_gen_row(row: dict) -> dict:
    out = dict(row)
    out["scores"] = _coerce_jsonb(out.get("scores")) or {}
    return out
