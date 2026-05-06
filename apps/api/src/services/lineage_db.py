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
